"""Authenticated Chatwoot ingress using the existing tenant-scoped durable inbox."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, TYPE_CHECKING

from app.channels.chatwoot import ChatwootSettings
from app.services.message_store import list_inbox, mark_inbox_consumed, push_inbox

if TYPE_CHECKING:
    from app.channels.chatwoot import ChatwootAdapter

logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 1_048_576
SIGNATURE_TOLERANCE_SECONDS = 300
RECEIPT_CHANNEL = "chatwoot_receipt"


class WebhookRejected(ValueError):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


def _positive_id(value: Any) -> int:
    if isinstance(value, bool):
        raise WebhookRejected("Chatwoot 消息标识无效", 400)
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise WebhookRejected("Chatwoot 消息标识无效", 400) from exc
    if result <= 0 or str(result) != str(value):
        raise WebhookRejected("Chatwoot 消息标识无效", 400)
    return result


def authenticate(raw: bytes, *, timestamp: str, signature: str, settings: ChatwootSettings) -> dict:
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise WebhookRejected("Chatwoot 回调过大", 413)
    if not settings.enabled or not settings.webhook_secret:
        raise WebhookRejected("Chatwoot 签名回调未启用", 403)
    if not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 12:
        raise WebhookRejected("Chatwoot 回调时间戳无效")
    if abs(time.time() - int(timestamp)) > SIGNATURE_TOLERANCE_SECONDS:
        raise WebhookRejected("Chatwoot 回调已过期")
    expected = "sha256=" + hmac.new(settings.webhook_secret.encode(),
                                    timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    if not signature.isascii() or not hmac.compare_digest(expected, signature):
        raise WebhookRejected("Chatwoot 回调签名无效")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebhookRejected("Chatwoot 回调不是有效 JSON", 400) from exc
    if not isinstance(payload, dict):
        raise WebhookRejected("Chatwoot 回调格式无效", 400)
    return payload


def store_event(payload: dict, *, settings: ChatwootSettings, team_id: int, delivery_id: str) -> dict:
    """Insert stable IDs; INSERT OR IGNORE preserves already-consumed duplicates."""
    event = payload.get("event")
    if event not in {"message_created", "message_updated"}:
        return {"accepted": True, "ignored": "unsupported_event"}
    account, inbox, conversation = payload.get("account"), payload.get("inbox"), payload.get("conversation")
    if not all(isinstance(item, dict) for item in (account, inbox, conversation)):
        raise WebhookRejected("Chatwoot 回调缺少 account / inbox / conversation", 400)
    if account.get("id") != settings.account_id or inbox.get("id") != settings.inbox_id:
        raise WebhookRejected("Chatwoot account / inbox 与团队绑定不匹配", 403)
    if conversation.get("inbox_id") != settings.inbox_id:
        raise WebhookRejected("Chatwoot 会话不属于绑定收件箱", 403)
    message_id, conversation_id = _positive_id(payload.get("id")), _positive_id(conversation.get("id"))
    if payload.get("private") is not False:
        return {"accepted": True, "ignored": "private_or_missing_visibility"}
    target = settings.target(conversation_id)
    sender = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
    message_type = payload.get("message_type")
    if isinstance(message_type, bool):
        raise WebhookRejected("Chatwoot message_type 无效", 400)
    metadata = {
        "provider": "chatwoot", "provider_message_id": str(message_id),
        "account_id": settings.account_id, "inbox_id": settings.inbox_id,
        "gateway_id": settings.gateway_id,
        "conversation_id": conversation_id, "provider_contact_id": sender.get("id"),
        "provider_source_id": payload.get("source_id"), "team_id": team_id,
        "provider_created_at": payload.get("created_at"),
    }
    if message_type in (0, "incoming") and event == "message_created":
        content = payload.get("content")
        # Preserve media metadata, but never ask the text-only reply runtime to
        # invent a response to an unread attachment.
        attachments = payload.get("attachments") or []
        metadata["attachments"] = attachments
        mid = push_inbox(
            "chatwoot", contact_id=target, direction="inbound", content=str(content or ""),
            contact_name=str(sender.get("name") or target),
            content_type="text" if isinstance(content, str) and content.strip() else "file",
            metadata=metadata, msg_id=f"chatwoot:{settings.gateway_id}:{settings.account_id}:{settings.inbox_id}:{message_id}",
            team_id=team_id,
        )
        return {"accepted": True, "message_id": mid, "kind": "inbound"}
    if message_type in (1, "outgoing"):
        attributes = payload.get("content_attributes") or {}
        if not isinstance(attributes, dict) or not attributes.get("kellai_request_id"):
            return {"accepted": True, "ignored": "external_outgoing_echo"}
        metadata["kellai_request_id"] = str(attributes["kellai_request_id"])
        # A separate inbox partition keeps status jobs durable through API outages.
        # Delivery IDs distinguish updates whose standard payload omits status.
        receipt_key = hashlib.sha256(delivery_id.encode()).hexdigest()[:32]
        mid = push_inbox(
            RECEIPT_CHANNEL, contact_id=target, direction="outbound", content="",
            metadata=metadata, msg_id=f"chatwoot-receipt:{settings.gateway_id}:{settings.account_id}:{message_id}:{receipt_key}",
            team_id=team_id,
        )
        return {"accepted": True, "message_id": mid, "kind": "receipt"}
    return {"accepted": True, "ignored": "non_incoming_event"}


async def reconcile_pending_receipts(adapter: ChatwootAdapter, *, team_id: int) -> None:
    from app.services.outbound_delivery import reconcile_receipt
    settings = adapter.settings()
    for row in list_inbox(RECEIPT_CHANNEL, limit=50, team_id=team_id):
        metadata = row.get("metadata", {})
        if (metadata.get("account_id") != settings.account_id or metadata.get("inbox_id") != settings.inbox_id
                or metadata.get("gateway_id") != settings.gateway_id):
            continue
        try:
            message_id = int(metadata["provider_message_id"])
            state = await adapter.message_status(int(metadata["conversation_id"]), message_id)
            if state != "unknown" and reconcile_receipt(
                team_id=team_id, channel_type="chatwoot", provider_message_id=str(message_id), state=state,
                provider_context={key: metadata[key] for key in ("gateway_id", "account_id", "inbox_id", "conversation_id")},
            ):
                mark_inbox_consumed([row["id"]], team_id=team_id)
        except Exception as exc:
            # Failed API lookup and unbound ACKs stay pending, never guessed or resent.
            logger.warning("Chatwoot 消息状态尚未确认: team=%s (%s)", team_id, type(exc).__name__)
