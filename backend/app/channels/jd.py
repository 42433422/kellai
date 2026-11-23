"""京东历史接入骨架。

原请求未形成完整OAuth授权与可验证聊天协议。本轮停止客户消息外发，
保留历史inbox消费；本地签名生成不代表平台鉴权。
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


_UNCONFIGURED_MSG = "京东渠道未配置（缺少 app_key / app_secret）"


def _app_key() -> str:
    return get_field("jd", "app_key")


def _app_secret() -> str:
    return get_field("jd", "app_secret")


class JdAdapter(ChannelAdapter):
    """京东渠道适配器。"""

    channel_type = "jd"

    def __init__(self) -> None:
        self._base_url: str = read_env("KELLAI_JD_BASE_URL", "https://api.jd.com")
        self._client: httpx.AsyncClient | None = None

    def _is_configured(self) -> bool:
        return bool(_app_key() and _app_secret())

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=15.0,
                headers={"User-Agent": "kellai-jd/1.0"},
            )
        return self._client

    @staticmethod
    def _sign(params: dict[str, Any], secret: str) -> str:
        """京东标准签名：参数按 key 排序拼接，MD5(secret + ... + secret) 大写。"""
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
            logger.warning("读取京东收件箱失败: %s", type(exc).__name__)
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
