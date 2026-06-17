"""微信渠道适配器。

当前服务端可直接打通的是企业微信群机器人 Webhook：前端保存
KELLAI_WECHAT_BOT_WEBHOOK 或渠道配置后，可通过统一消息接口发送。
接收侧复用 kellai_channel_inbox，微信/公众号/人工导入回调写入后由这里消费。
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

_UNCONFIGURED_MSG = "微信渠道未配置（缺少 bot_webhook）"


def _cfg(field: str, default: str = "") -> str:
    return get_field("wechat", field, default=default) or read_env(
        f"KELLAI_WECHAT_{field.upper()}",
        default=default,
    )


class WeChatAdapter(ChannelAdapter):
    """微信渠道适配器（Webhook 发送 + 收件箱接收）。"""

    channel_type = "wechat"

    def _bot_webhook(self) -> str:
        return _cfg("bot_webhook")

    def _is_configured(self) -> bool:
        return bool(self._bot_webhook())

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}

        content = (content or "").strip()
        if not content:
            return {"success": False, "message_id": "", "error": "消息内容为空"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.post(
                    self._bot_webhook(),
                    json={
                        "msgtype": "markdown",
                        "markdown": {"content": content},
                        "mentioned_list": list(kwargs.get("mentioned_list", []) or []),
                    },
                )
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            if resp.status_code >= 400 or int(body.get("errcode", 0)) != 0:
                return {
                    "success": False,
                    "message_id": "",
                    "error": f"微信机器人返回错误: HTTP {resp.status_code} body={body}",
                }
            return {
                "success": True,
                "message_id": str(body.get("msgid", "")),
                "error": "",
            }
        except Exception as exc:
            logger.warning("微信 send_message 失败: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        try:
            from app.services.message_store import list_inbox

            rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取微信收件箱失败: %s", exc)
            return []

        messages: list[UnifiedMessage] = []
        for row in rows:
            created_at = str(row.get("received_at", ""))
            if since and created_at and created_at <= since:
                continue
            messages.append(
                UnifiedMessage(
                    id=str(row["id"]),
                    customer_id=0,
                    channel_type=self.channel_type,
                    contact_id=str(row.get("contact_id", "")),
                    contact_name=str(row.get("contact_name", "")),
                    direction=str(row.get("direction", "inbound")),
                    content=str(row.get("content", "")),
                    content_type=str(row.get("content_type", "text")),
                    metadata=dict(row.get("metadata", {}) or {}),
                    created_at=created_at or datetime.now(timezone.utc).isoformat(),
                )
            )
        return messages

    async def get_contacts(self, keyword: str = "", limit: int = 80) -> list[dict]:
        try:
            from app.services.message_store import list_inbox

            rows = list_inbox(self.channel_type, limit=500, include_consumed=True)
        except Exception:
            return []

        seen: dict[str, dict] = {}
        kw = keyword.lower()
        for row in rows:
            cid = str(row.get("contact_id", "")).strip()
            if not cid or cid in seen:
                continue
            name = str(row.get("contact_name", "")).strip() or cid
            if kw and kw not in name.lower() and kw not in cid.lower():
                continue
            seen[cid] = {"id": cid, "name": name, "channel": self.channel_type}
            if len(seen) >= int(limit):
                break
        return list(seen.values())

    async def test_connection(self) -> dict:
        if not self._is_configured():
            return {"connected": False, "message": _UNCONFIGURED_MSG}
        return {"connected": True, "message": "微信机器人 Webhook 已配置"}
