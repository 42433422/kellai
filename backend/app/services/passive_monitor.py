"""微信群被动轮询 / LLM 就绪探测。

统一通过 channels.registry 走 WeChatAdapter，不再直接调 wechat_bridge。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.pipeline import _pipeline_roots

logger = logging.getLogger(__name__)

_THINKING_MARKERS = re.compile(
    r"(^|\n)\s*(思考|Thought|Let me think|我需要先|分析如下)",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_root() -> Path:
    root = _pipeline_roots()[0].parent / "passive_poll"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _config_file(customer_id: int) -> Path:
    return _config_root() / f"{int(customer_id)}.json"


def _load_config(customer_id: int) -> dict[str, Any]:
    path = _config_file(customer_id)
    if not path.is_file():
        return {"customer_id": int(customer_id), "poll_enabled": False, "poll_interval_sec": 60}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"customer_id": int(customer_id), "poll_enabled": False, "poll_interval_sec": 60}
    return raw if isinstance(raw, dict) else {}


def _save_config(data: dict[str, Any]) -> dict[str, Any]:
    uid = int(data.get("customer_id") or data.get("market_user_id") or 0)
    path = _config_file(uid)
    data = dict(data)
    data["customer_id"] = uid
    data["updated_at"] = _now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def _llm_configured() -> tuple[bool, str]:
    try:
        from app.services.llm_config import effective_config

        cfg = effective_config()
        if cfg.get("api_key"):
            return True, f"已配置 {cfg.get('provider') or 'LLM'}（{cfg.get('source') or 'saved_config'}）"
    except Exception:
        logger.debug("读取 LLM 配置失败", exc_info=True)
    return False, "请在设置页保存真实 LLM API Key，或配置 DEEPSEEK_API_KEY/OPENAI_API_KEY 等环境变量"


def probe_passive_llm_ready() -> dict[str, Any]:
    ready, message = _llm_configured()
    try:
        from app.services.llm_config import public_config

        data = public_config()
        data["ready"] = ready
        if not ready:
            data["connected"] = False
        data["message"] = data.get("message") or message
        return data
    except Exception:
        return {"ready": ready, "connected": False, "message": message}


def get_passive_poll_config(customer_id: int, *, username: str = "") -> dict[str, Any]:
    _ = username
    cfg = _load_config(int(customer_id))
    cfg.setdefault("poll_enabled", False)
    cfg.setdefault("poll_interval_sec", 60)
    return cfg


def save_passive_poll_config(
    customer_id: int,
    *,
    username: str = "",
    poll_enabled: bool = False,
    poll_interval_sec: int = 60,
) -> dict[str, Any]:
    _ = username
    cfg = _load_config(int(customer_id))
    cfg.update(
        {
            "customer_id": int(customer_id),
            "poll_enabled": bool(poll_enabled),
            "poll_interval_sec": max(10, min(600, int(poll_interval_sec))),
        }
    )
    return _save_config(cfg)


def reset_passive_watch(customer_id: int, *, username: str = "") -> dict[str, Any]:
    _ = username
    cfg = _load_config(int(customer_id))
    cfg["watch_reset_at"] = _now_iso()
    cfg["last_seen_message_id"] = ""
    return _save_config(cfg)


def _run_async(coro):
    """在同步上下文中安全运行异步协程（避免与现有事件循环冲突）。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 已在 async 上下文内：返回原始协程，让上层 await
            return coro
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _fetch_wecom_messages(customer_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """通过 channels.registry 拿 WeComAdapter，统一拉取企微消息。

    返回值是 dict 列表（与历史 build_starred_group_feed 行为兼容）。
    """
    from app.channels.registry import ChannelRegistry

    try:
        adapter = ChannelRegistry().get("wecom")
    except KeyError as exc:
        logger.warning("wecom 渠道未注册: %s", exc)
        return []

    try:
        msgs = _run_async(adapter.receive_messages(since="", limit=int(limit)))  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("wecom adapter 拉取消息失败: %s", exc)
        return []

    uid = int(customer_id)
    out: list[dict[str, Any]] = []
    for m in msgs:
        if uid > 0 and int(getattr(m, "customer_id", 0) or 0) != uid:
            continue
        out.append(
            {
                "id": getattr(m, "id", ""),
                "customer_id": getattr(m, "customer_id", 0),
                "channel_type": getattr(m, "channel_type", "wecom"),
                "contact_id": getattr(m, "contact_id", ""),
                "contact_name": getattr(m, "contact_name", ""),
                "direction": getattr(m, "direction", "inbound"),
                "content": getattr(m, "content", ""),
                "message": getattr(m, "content", ""),
                "content_type": getattr(m, "content_type", "text"),
                "created_at": getattr(m, "created_at", ""),
                "metadata": getattr(m, "metadata", {}) or {},
            }
        )
    return out


def passive_poll_once(
    *,
    customer_id: int,
    username: str = "",
    dry_run: bool = True,
    auto_reply: bool = True,
    max_replies: int = 0,
    use_llm: bool = True,
    skip_sync: bool = False,
) -> dict[str, Any]:
    """单次被动轮询：统一走 WeChatAdapter（不再直调 wechat_bridge）。"""
    _ = username
    uid = int(customer_id)

    # 兼容旧 skip_sync 语义：true 时跳过预拉取，否则先取一次消息
    if not skip_sync:
        feed = _fetch_wecom_messages(uid, limit=20)
    else:
        feed = []

    texts = [str(x.get("content") or x.get("message") or "") for x in feed if x.get("content") or x.get("message")]
    detected = len(texts)
    ready, llm_msg = _llm_configured()
    llm_error = "" if ready or not use_llm else llm_msg
    replies: list[dict[str, Any]] = []
    if auto_reply and not dry_run and detected > 0 and texts:
        reply_text = "您好，已收到消息，客服稍后回复。"
        reply_source = "template"
        if use_llm and ready:
            reply_source = "llm_stub"
        replies.append(
            {
                "reply": reply_text,
                "reply_source": reply_source,
                "llm_error": llm_error,
            }
        )
    cfg = _load_config(uid)
    cfg["last_poll_at"] = _now_iso()
    _save_config(cfg)
    return {
        "success": True,
        "dry_run": dry_run,
        "detected_count": detected,
        "replies": replies[: max(0, int(max_replies))] if max_replies else replies[:1],
        "llm_ready": ready,
        "message_count": detected,
    }
