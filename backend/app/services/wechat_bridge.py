"""微信群 ↔ 客户绑定与星标摘要（客来来独立实现 · 可接解密库）。

⚠️ 已废弃：仅保留向后兼容能力，新功能请走 channels.registry.get("wechat")
拿 WeChatAdapter。后续会逐步迁移。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.services.pipeline import _pipeline_roots

logger = logging.getLogger(__name__)

_DEPRECATION_NOTICE = (
    "wechat_bridge 已废弃，请改用 channels.registry.get('wechat') 拿 WeChatAdapter。"
    "本模块仅保留兼容旧调用方，不再新增功能。"
)


def _bindings_root() -> Path:
    root = _pipeline_roots()[0].parent / "wechat_bindings"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _bindings_file(customer_id: int) -> Path:
    return _bindings_root() / f"{int(customer_id)}.json"


def list_group_contacts(keyword: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    _ = keyword
    _ = limit
    logger.debug(_DEPRECATION_NOTICE)
    return []


def get_bindings_for_user(customer_id: int) -> list[dict[str, Any]]:
    path = _bindings_file(int(customer_id))
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("contacts") if isinstance(raw, dict) else raw
    return list(items) if isinstance(items, list) else []


def save_bindings_for_user(customer_id: int, contact_ids: list[Any]) -> dict[str, Any]:
    uid = int(customer_id)
    ids = [int(x) for x in contact_ids if str(x).strip().isdigit()]
    path = _bindings_file(uid)
    payload = {"customer_id": uid, "contact_ids": ids, "contacts": [{"id": i} for i in ids]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"success": True, "data": {"contact_ids": ids}}


def build_starred_group_feed(limit: int = 10, customer_id: int | None = None) -> list[dict[str, Any]]:
    _ = limit
    _ = customer_id
    logger.debug(_DEPRECATION_NOTICE)
    return []


def sync_group_messages(
    customer_id: int | None = None,
    group_limit: int = 30,
    message_limit: int = 80,
    force_refresh: bool = False,
) -> dict[str, Any]:
    _ = customer_id
    _ = group_limit
    _ = message_limit
    _ = force_refresh
    logger.debug(_DEPRECATION_NOTICE)
    return {
        "success": True,
        "synced": 0,
        "failed": 0,
        "message": "wechat_bridge 已废弃，请改用 WeChatAdapter；微信解密库未配置",
    }
