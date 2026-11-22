"""淘宝/天猫历史接入骨架。

TMC事件生产不是买家私聊。本轮停止未经验证的客户消息外发，
保留原配置工具和历史inbox消费；能力以capabilities.py为准。
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
    return get_field("taobao", "app_key")


def _app_secret() -> str:
    return get_field("taobao", "app_secret")


def _session_key() -> str:
    return get_field("taobao", "session_key")


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
        """The historical request is not an authorized customer chat protocol."""
        from app.channels.capabilities import CAPABILITIES
        return {"success": False, "message_id": "", "delivery_state": "failed",
                "definitely_not_sent": True, "retryable": False,
                "error": CAPABILITIES[self.channel_type]["limitations"][0]}

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        try:
            from app.services.message_store import list_inbox
            rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取淘宝收件箱失败: %s", type(exc).__name__)
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

    async def test_connection(self, **kwargs) -> dict:
        from app.channels.capabilities import CAPABILITIES
        return {"connected": False, "verification_level": "unverified",
                "message": CAPABILITIES[self.channel_type]["limitations"][0]}
