"""LINE 渠道适配器（真实 HTTP API 实现 · LINE Messaging API）。

参考：https://developers.line.biz/en/docs/messaging-api/
- 鉴权：channel_access_token（Bearer）
- 发送：POST /v2/bot/message/push
- 接收：webhook → kellai_channel_inbox

环境变量（或前端配置）：
- KELLAI_LINE_CHANNEL_ACCESS_TOKEN
- KELLAI_LINE_CHANNEL_SECRET（用于 webhook 验签，可选）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.config_store import get_field
from app.channels.http_client import read_env

logger = logging.getLogger(__name__)


_UNCONFIGURED_MSG = "LINE 渠道未配置（缺少 channel_access_token）"


def _channel_access_token() -> str:
    return get_field("line", "channel_access_token", read_env("KELLAI_LINE_CHANNEL_ACCESS_TOKEN"))


class LineAdapter(ChannelAdapter):
    """LINE Messaging API 适配器。"""

    channel_type = "line"

    def __init__(self) -> None:
        self._base_url: str = read_env("KELLAI_LINE_BASE_URL", "https://api.line.me")
        self._client: httpx.AsyncClient | None = None

    def _is_configured(self) -> bool:
        return bool(_channel_access_token())

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=15.0,
                headers={
                    "User-Agent": "kellai-line/1.0",
                    "Authorization": f"Bearer {_channel_access_token()}",
                },
            )
        return self._client

    # ----------------- send_message -----------------

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        """contact_id: LINE user_id。"""
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}
        if not contact_id or not (content or "").strip():
            return {"success": False, "message_id": "", "error": "参数不完整"}
        try:
            client = await self._get_client()
            payload = {
                "to": contact_id,
                "messages": [{"type": "text", "text": content[:5000]}],
            }
            resp = await client.post("/v2/bot/message/push", json=payload)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            if resp.status_code >= 400 or "message" in body:
                return {
                    "success": False,
                    "message_id": "",
                    "error": f"errcode={body.get('code', resp.status_code)} {body.get('message', '')}",
                }
            return {"success": True, "message_id": "", "error": ""}
        except Exception as exc:
            logger.warning("LINE send_message 异常: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        try:
            from app.services.message_store import list_inbox
            rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取 LINE 收件箱失败: %s", exc)
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
            client = await self._get_client()
            # 调 /v2/bot/info 验证 token（不消耗额度）
            resp = await client.get("/v2/bot/info")
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            if resp.status_code == 200 and body.get("userId"):
                return {
                    "connected": True,
                    "message": f"LINE Bot {body.get('basicId') or body.get('userId', '?')} 鉴权通过",
                }
            return {
                "connected": False,
                "message": f"errcode={body.get('code', resp.status_code)} {body.get('message', '')}",
            }
        except Exception as exc:
            return {"connected": False, "message": f"LINE 连接失败: {exc}"}
