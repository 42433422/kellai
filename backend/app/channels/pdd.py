"""拼多多历史接入骨架。

原发送请求缺少完整开放平台方法和授权。本轮停止客户消息外发，
保留历史inbox消费；能力以capabilities.py为准。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.config_store import get_field
from app.channels.http_client import CachedToken, read_env

logger = logging.getLogger(__name__)


_UNCONFIGURED_MSG = "拼多多渠道未配置（缺少 client_id / client_secret）"


def _client_id() -> str:
    return get_field("pdd", "client_id")


def _client_secret() -> str:
    return get_field("pdd", "client_secret")


class PddAdapter(ChannelAdapter):
    """拼多多渠道适配器。"""

    channel_type = "pdd"

    def __init__(self) -> None:
        self._base_url: str = read_env("KELLAI_PDD_BASE_URL", "https://open-api.pinduoduo.com")
        self._client: httpx.AsyncClient | None = None
        self._token: CachedToken | None = None

    def _is_configured(self) -> bool:
        return bool(_client_id() and _client_secret())

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=15.0,
                headers={"User-Agent": "kellai-pdd/1.0"},
            )
        return self._client

    async def _fetch_token(self) -> tuple[str, int]:
        """拼多多 pop 鉴权：client_credentials 风格。"""
        client = await self._get_client()
        resp = await client.post(
            "/oauth/token",
            data={
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "grant_type": "client_credentials",
            },
        )
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        token = str(body.get("access_token", ""))
        ttl = int(body.get("expires_in", 7200))
        if not token:
            raise RuntimeError("拼多多 token 拉取失败")
        return token, ttl

    def _ensure_token_cache(self) -> CachedToken:
        if self._token is None:
            self._token = CachedToken(self._fetch_token, ttl_sec=7000)
        return self._token

    async def _on_token_invalid(self) -> None:
        if self._token is not None:
            self._token.invalidate()

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
            logger.warning("读取拼多多收件箱失败: %s", type(exc).__name__)
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
