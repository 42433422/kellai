"""Thin Chatwoot v4.20.1 bridge; Chatwoot owns provider credentials and transports.

The application API accepts a message into its queue. This does not prove that
the underlying channel delivered it. No mutation is automatically retried.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.channels import config_store
from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.http_client import ChannelHTTPError, checked_json, send_error
from app.services.tenant_context import current_team_id


CHATWOOT_VERSION = "4.20.1"
CHATWOOT_COMMIT = "b2f94636d325a126a67c6c4c808303d8aa8cbeea"


@dataclass(frozen=True)
class ChatwootSettings:
    base_url: str
    account_id: int
    inbox_id: int
    api_access_token: str
    webhook_secret: str
    enabled: bool

    @classmethod
    def load(cls, saved: dict | None = None) -> ChatwootSettings:
        saved = config_store.get_all("chatwoot") if saved is None else saved
        cfg = saved.get("config", {})
        base_url = str(cfg.get("base_url") or "").strip().rstrip("/")
        parsed = urlsplit(base_url)
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.scheme not in {"https", "http"}
                or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
            raise ValueError("Chatwoot base_url 需为 HTTPS 地址；本机开发可用 HTTP loopback")
        try:
            account_id, inbox_id = int(cfg.get("account_id", 0)), int(cfg.get("inbox_id", 0))
        except (ValueError, TypeError) as exc:
            raise ValueError("Chatwoot account_id / inbox_id 必须为正整数") from exc
        token = str(cfg.get("api_access_token") or "").strip()
        if account_id <= 0 or inbox_id <= 0 or not token:
            raise ValueError("Chatwoot 缺少 account_id / inbox_id / api_access_token")
        return cls(base_url, account_id, inbox_id, token,
                   str(cfg.get("webhook_secret") or ""), bool(saved.get("enabled", False)))

    def target(self, conversation_id: int) -> str:
        return f"chatwoot:{self.gateway_id}:{self.account_id}:{self.inbox_id}:{conversation_id}"

    @property
    def gateway_id(self) -> str:
        return hashlib.sha256(self.base_url.encode()).hexdigest()[:16]

    def conversation_id(self, contact_id: str) -> int:
        matched = re.fullmatch(r"chatwoot:([a-f0-9]{16}):([1-9][0-9]*):([1-9][0-9]*):([1-9][0-9]*)", contact_id)
        if (not matched or matched.group(1) != self.gateway_id
                or tuple(map(int, matched.groups()[1:3])) != (self.account_id, self.inbox_id)):
            raise ValueError("Chatwoot 发送目标不属于本团队绑定的 account / inbox")
        return int(matched.group(4))


class ChatwootAdapter(ChannelAdapter):
    channel_type = "chatwoot"

    def __init__(self) -> None:
        self._team_id = current_team_id()
        self._configuration = config_store.get_all("chatwoot")
        self._client: httpx.AsyncClient | None = None

    def settings(self) -> ChatwootSettings:
        if current_team_id() != self._team_id or self._team_id <= 0:
            raise ValueError("Chatwoot 必须在创建该适配器的团队上下文中使用")
        return ChatwootSettings.load(self._configuration)

    async def _get_client(self) -> httpx.AsyncClient:
        settings = self.settings()
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.base_url + "/", timeout=15.0, follow_redirects=False,
                headers={"Authorization": f"Bearer {settings.api_access_token}",
                         "Accept": "application/json", "User-Agent": "kellai-chatwoot/1.0"},
            )
        return self._client

    async def _conversation(self, settings: ChatwootSettings, conversation_id: int) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.get(f"api/v1/accounts/{settings.account_id}/conversations/{conversation_id}")
        body = checked_json(response)
        if body.get("id") != conversation_id or body.get("inbox_id") != settings.inbox_id:
            raise ValueError("Chatwoot 远端会话不属于绑定收件箱")
        return body

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        # Everything before POST is a safe preflight. Failure cannot have sent a message.
        try:
            settings = self.settings()
            if not settings.enabled:
                raise ValueError("Chatwoot 渠道未启用")
            if not content or not content.strip():
                raise ValueError("消息内容为空")
            conversation_id = settings.conversation_id(contact_id)
            conversation = await self._conversation(settings, conversation_id)
            if conversation.get("can_reply") is False:
                raise ValueError("Chatwoot 会话当前不允许回复；请检查平台回复窗口及授权")
            client = await self._get_client()
        except Exception as exc:
            result = send_error(exc, definitely_not_sent=True)
            result.update(delivery_state="failed", definitely_not_sent=True)
            return result

        payload: dict[str, Any] = {"content": content, "message_type": "outgoing",
                                   "private": False, "content_type": "text"}
        request_id = str(kwargs.get("idempotency_key") or "")
        if request_id:
            # echo_id is transient, not a provider idempotency guarantee. Persist
            # correlation separately; uncertain sends require reconciliation.
            payload["echo_id"] = request_id
            payload["content_attributes"] = {"kellai_request_id": request_id}
        try:
            response = await client.post(
                f"api/v1/accounts/{settings.account_id}/conversations/{conversation_id}/messages", json=payload,
            )
            body = checked_json(response)
            message_id = body.get("id")
            if (not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0
                    or body.get("inbox_id") != settings.inbox_id
                    or body.get("conversation_id") != conversation_id):
                return send_error("Chatwoot 响应缺少有效消息凭据，发送结果未知")
            return {"success": True, "message_id": str(message_id), "error": "",
                    "delivery_state": "accepted", "provider": "chatwoot", "retryable": False,
                    "conversation_id": conversation_id, "inbox_id": settings.inbox_id,
                    "account_id": settings.account_id, "gateway_id": settings.gateway_id}
        except Exception as exc:
            return send_error(exc)

    async def message_status(self, conversation_id: int, message_id: int) -> str:
        """The pinned webhook omits status; read the exact message from the API."""
        settings = self.settings()
        await self._conversation(settings, conversation_id)
        client = await self._get_client()
        body = checked_json(await client.get(
            f"api/v1/accounts/{settings.account_id}/conversations/{conversation_id}/messages",
            params={"after": message_id, "before": message_id + 1},
        ))
        rows = body.get("payload")
        if not isinstance(rows, list):
            return "unknown"
        for row in rows:
            if not isinstance(row, dict):
                continue
            if (row.get("id") == message_id and row.get("inbox_id") == settings.inbox_id
                    and row.get("conversation_id") == conversation_id
                    and row.get("message_type") in (1, "outgoing") and not row.get("private", False)):
                status = row.get("status")
                return status if status in {"sent", "delivered", "read", "failed"} else "unknown"
        return "unknown"

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        from app.services.message_store import list_inbox
        from app.services.chatwoot_gateway import reconcile_pending_receipts
        self.settings()
        await reconcile_pending_receipts(self, team_id=self._team_id)
        rows = list_inbox(self.channel_type, limit=max(1, min(int(limit), 500)), team_id=self._team_id)
        return [UnifiedMessage(
            id=row["id"], customer_id=0, channel_type=self.channel_type,
            contact_id=row["contact_id"], contact_name=row["contact_name"], direction=row["direction"],
            content=row["content"], content_type=row["content_type"], metadata=row["metadata"],
            created_at=row["received_at"],
        ) for row in rows if not since or row["received_at"] > since]

    async def get_contacts(self, keyword: str = "", limit: int = 80) -> list[dict]:
        from app.services.message_store import list_inbox
        self.settings()
        seen = {}
        for row in list_inbox(self.channel_type, limit=500, include_consumed=True, team_id=self._team_id):
            target, name = row["contact_id"], row["contact_name"] or row["contact_id"]
            if target and (not keyword or keyword.lower() in name.lower()):
                seen.setdefault(target, {"id": target, "name": name, "channel": self.channel_type})
        return list(seen.values())[:max(1, min(limit, 500))]

    async def test_connection(self, **kwargs: Any) -> dict:
        try:
            settings = self.settings()
            client = await self._get_client()
            body = checked_json(await client.get(
                f"api/v1/accounts/{settings.account_id}/inboxes/{settings.inbox_id}",
            ))
            if body.get("id") != settings.inbox_id:
                raise ValueError("Chatwoot 返回的 inbox 与配置不一致")
            return {"connected": True, "verification_level": "authenticated",
                    "message": "Chatwoot 收件箱授权验证通过；真实收发及平台送达尚需端到端验收",
                    "inbox_name": str(body.get("name") or ""), "provider_channel": body.get("channel_type"),
                    "webhook_configured": bool(settings.webhook_secret)}
        except Exception as exc:
            return {"connected": False, "verification_level": "unverified",
                    "message": f"Chatwoot 连接失败: {type(exc).__name__}"}
