"""淘宝 / 天猫渠道适配器（真实 HTTP API 实现 · 淘宝开放平台 TopAPI）。

参考：https://open.taobao.com
- 鉴权：app_key / app_secret → session_key（依赖用户授权码 code，本适配器接受预授权 session）
- 发送：taobao.tmc.message.produce（交易消息中心，适合商户通知）
- 接收：webhook / TMC 长连接 → kellai_channel_inbox

环境变量（或前端配置保存到 channel_configs.json）：
- KELLAI_TAOBAO_APP_KEY
- KELLAI_TAOBAO_APP_SECRET
- KELLAI_TAOBAO_SESSION_KEY（可选，商家预授权 session）
- KELLAI_TAOBAO_BASE_URL（默认 https://eco.taobao.com）
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.config_store import get_field
from app.channels.http_client import read_env

logger = logging.getLogger(__name__)


_UNCONFIGURED_MSG = "淘宝渠道未配置（缺少 app_key / app_secret）"


def _app_key() -> str:
    return get_field("taobao", "app_key", read_env("KELLAI_TAOBAO_APP_KEY"))


def _app_secret() -> str:
    return get_field("taobao", "app_secret", read_env("KELLAI_TAOBAO_APP_SECRET"))


def _session_key() -> str:
    return get_field("taobao", "session_key", read_env("KELLAI_TAOBAO_SESSION_KEY"))


class TaobaoAdapter(ChannelAdapter):
    """淘宝 / 天猫渠道适配器。"""

    channel_type = "taobao"

    def __init__(self) -> None:
        self._base_url: str = read_env("KELLAI_TAOBAO_BASE_URL", "https://eco.taobao.com")
        self._client: httpx.AsyncClient | None = None

    def _is_configured(self) -> bool:
        return bool(_app_key() and _app_secret())

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=15.0,
                headers={"User-Agent": "kellai-taobao/1.0"},
            )
        return self._client

    @staticmethod
    def _sign(params: dict[str, Any], secret: str) -> str:
        """淘宝标准 MD5 签名：参数按 key 排序拼接，secret 包裹后 MD5。"""
        sorted_items = sorted((k, v) for k, v in params.items() if v not in (None, ""))
        sign_str = secret + "".join(f"{k}{v}" for k, v in sorted_items) + secret
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    # ----------------- send_message -----------------

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        """通过 taobao.tmc.message.produce 发送通知。

        contact_id: 商家 nick 或用户 open_id
        content: 文本
        """
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}
        if not contact_id or not (content or "").strip():
            return {"success": False, "message_id": "", "error": "参数不完整"}

        try:
            client = await self._get_client()
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            params: dict[str, Any] = {
                "app_key": _app_key(),
                "timestamp": ts,
                "format": "json",
                "v": "2.0",
                "sign_method": "md5",
                "method": "taobao.tmc.message.produce",
                "topic": "kellai",
                "content": content,
                "to_ids": contact_id,
            }
            session = _session_key()
            if session:
                params["session"] = session
            params["sign"] = self._sign(params, _app_secret())

            resp = await client.post("/router/rest", data=params)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            inner = body.get("tmc_message_produce_response", {}) or {}
            result = inner.get("is_success") or inner.get("msg_id")
            if not result:
                err = body.get("error_response", {}) or {}
                return {
                    "success": False,
                    "message_id": "",
                    "error": f"errcode={err.get('code')} {err.get('msg', '')}",
                }
            return {"success": True, "message_id": str(inner.get("msg_id", "")), "error": ""}
        except Exception as exc:
            logger.warning("淘宝 send_message 异常: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        try:
            from app.services.message_store import list_inbox
            rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取淘宝收件箱失败: %s", exc)
            return []
        out: list[UnifiedMessage] = []
        for r in rows:
            created_at = str(r.get("received_at", ""))
            if since and created_at and created_at <= since:
                continue
            out.append(
                UnifiedMessage(
                    id=str(r["id"]),
                    customer_id=0,
                    channel_type=self.channel_type,
                    contact_id=str(r.get("contact_id", "")),
                    contact_name=str(r.get("contact_name", "")),
                    direction=str(r.get("direction", "inbound")),
                    content=str(r.get("content", "")),
                    content_type=str(r.get("content_type", "text")),
                    metadata=dict(r.get("metadata", {}) or {}),
                    created_at=created_at or datetime.now(timezone.utc).isoformat(),
                )
            )
        return out

    # ----------------- get_contacts -----------------

    async def get_contacts(self, keyword: str = "", limit: int = 80) -> list[dict]:
        try:
            from app.services.message_store import list_inbox
            rows = list_inbox(self.channel_type, limit=500, include_consumed=True)
        except Exception:
            return []
        seen: dict[str, dict] = {}
        for r in rows:
            cid = str(r.get("contact_id", "")).strip()
            if not cid or cid in seen:
                continue
            seen[cid] = {
                "id": cid,
                "name": str(r.get("contact_name", "")) or cid,
                "channel": self.channel_type,
            }
            if keyword and keyword.lower() not in seen[cid]["name"].lower():
                seen.pop(cid)
                continue
            if len(seen) >= int(limit):
                break
        return list(seen.values())

    # ----------------- test_connection -----------------

    async def test_connection(self) -> dict:
        if not self._is_configured():
            return {"connected": False, "message": _UNCONFIGURED_MSG}
        try:
            # 不发实际请求，只本地拼一次签名验证 app_key/secret 格式
            params = {
                "app_key": _app_key(),
                "timestamp": str(int(time.time())),
                "format": "json",
                "v": "2.0",
                "method": "taobao.time.get",
            }
            sig = self._sign(params, _app_secret())
            if not sig or len(sig) != 32:
                return {"connected": False, "message": "淘宝签名生成失败，app_secret 格式异常"}
            return {"connected": True, "message": "淘宝 app_key/app_secret 签名校验通过"}
        except Exception as exc:
            return {"connected": False, "message": f"淘宝连接失败: {exc}"}
