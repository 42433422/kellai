"""WhatsApp 渠道适配器（真实 HTTP API 实现 · Meta WhatsApp Business Cloud API）。

参考：https://developers.facebook.com/docs/whatsapp/cloud-api
- 鉴权：永久 access_token（System User 或 Business App）
- 发送：POST /{phone_number_id}/messages
- 接收：webhook → kellai_channel_inbox

环境变量（或前端配置）：
- KELLAI_WHATSAPP_PHONE_NUMBER_ID
- KELLAI_WHATSAPP_ACCESS_TOKEN
- KELLAI_WHATSAPP_BUSINESS_ID
- KELLAI_WHATSAPP_BASE_URL（默认 https://graph.facebook.com/v20.0）
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


_UNCONFIGURED_MSG = "WhatsApp 渠道未配置（缺少 phone_number_id / access_token）"


def _phone_number_id() -> str:
    return get_field("whatsapp", "phone_number_id", read_env("KELLAI_WHATSAPP_PHONE_NUMBER_ID"))


def _access_token() -> str:
    return get_field("whatsapp", "access_token", read_env("KELLAI_WHATSAPP_ACCESS_TOKEN"))


class WhatsAppAdapter(ChannelAdapter):
    """WhatsApp Business Cloud API 适配器。"""

    channel_type = "whatsapp"

    def __init__(self) -> None:
        self._base_url: str = read_env("KELLAI_WHATSAPP_BASE_URL", "https://graph.facebook.com/v20.0")
        self._client: httpx.AsyncClient | None = None

    def _is_configured(self) -> bool:
        return bool(_phone_number_id() and _access_token())

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=20.0,
                headers={
                    "User-Agent": "kellai-whatsapp/1.0",
                    "Authorization": f"Bearer {_access_token()}",
                },
            )
        return self._client

    # ----------------- send_message -----------------

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        """通过 Cloud API 发送 text 消息。"""
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}
        if not contact_id or not (content or "").strip():
            return {"success": False, "message_id": "", "error": "参数不完整"}
        try:
            client = await self._get_client()
            payload = {
                "messaging_product": "whatsapp",
                "to": contact_id,
                "type": "text",
                "text": {"body": content[:4096]},
            }
            resp = await client.post(
                f"/{_phone_number_id()}/messages",
                json=payload,
            )
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            if resp.status_code >= 400 or "error" in body:
                err = body.get("error", {}) or {}
                return {
                    "success": False,
                    "message_id": "",
                    "error": f"errcode={err.get('code')} {err.get('message', '')}",
                }
            msg_id = ""
            msgs = body.get("messages", []) or []
            if msgs:
                msg_id = str(msgs[0].get("id", ""))
            return {"success": True, "message_id": msg_id, "error": ""}
        except Exception as exc:
            logger.warning("WhatsApp send_message 异常: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        try:
            from app.services.message_store import list_inbox
            rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取 WhatsApp 收件箱失败: %s", exc)
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
            # 真实接口：拉取 phone_number 元信息验证 token
            resp = await client.get(f"/{_phone_number_id()}")
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            if resp.status_code == 200 and body.get("id"):
                return {
                    "connected": True,
                    "message": f"WhatsApp phone_number {body.get('display_phone_number', _phone_number_id())} 鉴权通过",
                }
            err = body.get("error", {}) or {}
            return {
                "connected": False,
                "message": f"errcode={err.get('code')} {err.get('message', '')}",
            }
        except Exception as exc:
            return {"connected": False, "message": f"WhatsApp 连接失败: {exc}"}
