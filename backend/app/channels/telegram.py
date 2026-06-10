"""Telegram 渠道适配器（真实 HTTP API 实现 · Telegram Bot API）。

参考：https://core.telegram.org/bots/api
- 鉴权：bot_token（URL 中携带）
- 发送：sendMessage
- 接收：getUpdates（长轮询）或 webhook

环境变量（或前端配置）：
- KELLAI_TELEGRAM_BOT_TOKEN
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


_UNCONFIGURED_MSG = "Telegram 渠道未配置（缺少 bot_token）"


def _bot_token() -> str:
    return get_field("telegram", "bot_token", read_env("KELLAI_TELEGRAM_BOT_TOKEN"))


class TelegramAdapter(ChannelAdapter):
    """Telegram Bot API 适配器。"""

    channel_type = "telegram"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _is_configured(self) -> bool:
        return bool(_bot_token())

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"https://api.telegram.org/bot{_bot_token()}",
                timeout=20.0,
                headers={"User-Agent": "kellai-telegram/1.0"},
            )
        return self._client

    # ----------------- send_message -----------------

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        """contact_id: Telegram chat_id。content: 文本。"""
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}
        if not contact_id or not (content or "").strip():
            return {"success": False, "message_id": "", "error": "参数不完整"}
        try:
            client = await self._get_client()
            payload: dict[str, Any] = {
                "chat_id": contact_id,
                "text": content[:4096],
            }
            if kwargs.get("parse_mode"):
                payload["parse_mode"] = str(kwargs["parse_mode"])
            resp = await client.post("/sendMessage", json=payload)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            if not body.get("ok"):
                return {
                    "success": False,
                    "message_id": "",
                    "error": f"errcode={body.get('error_code')} {body.get('description', '')}",
                }
            result = body.get("result", {}) or {}
            return {"success": True, "message_id": str(result.get("message_id", "")), "error": ""}
        except Exception as exc:
            logger.warning("Telegram send_message 异常: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        """从收件箱读（webhook 入库）；同时可调 getUpdates 拉取一次。"""
        try:
            from app.services.message_store import list_inbox
            rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取 Telegram 收件箱失败: %s", exc)
            rows = []
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
            resp = await client.get("/getMe")
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            if body.get("ok"):
                result = body.get("result", {}) or {}
                return {
                    "connected": True,
                    "message": f"Telegram Bot @{result.get('username', '?')} 鉴权通过",
                }
            return {
                "connected": False,
                "message": f"errcode={body.get('error_code')} {body.get('description', '')}",
            }
        except Exception as exc:
            return {"connected": False, "message": f"Telegram 连接失败: {exc}"}
