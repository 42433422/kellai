"""Durable delivery receipts on the existing tenant-scoped message database.

The intent is committed before any external side effect. An interrupted attempt
is never sent again automatically: callers recover its receipt, not its network
request. Provider acceptance and final delivery/read receipts remain distinct.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from app.channels.base import UnifiedMessage
from app.services.crm_store import _crm_db_path
from app.services.tenant_context import resolve_team_id, tenant_scope


class DeliveryConflict(ValueError):
    """A request key was reused for a different recipient or message."""


class DeliveryLeaseError(ValueError):
    """A result did not belong to the holder of this delivery attempt."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema() -> None:
    with sqlite3.connect(str(_crm_db_path()), timeout=30) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS kellai_outbound_deliveries (
                team_id INTEGER NOT NULL,
                request_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                channel_type TEXT NOT NULL,
                message_id TEXT NOT NULL,
                status TEXT NOT NULL,
                delivery_token TEXT NOT NULL,
                lease_until TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',
                provider_message_id TEXT NOT NULL DEFAULT '',
                provider_state TEXT NOT NULL DEFAULT '',
                projected INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (team_id, request_id)
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbound_provider_receipt "
            "ON kellai_outbound_deliveries(team_id, channel_type, provider_message_id)"
        )


@contextmanager
def _connect():
    ensure_schema()
    conn = sqlite3.connect(str(_crm_db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _request_key(value: str) -> str:
    key = str(value or "").strip()
    if not key or len(key) > 200:
        raise ValueError("idempotency_key 必须为 1 至 200 个字符")
    return key


def _payload(message: UnifiedMessage, team_id: int) -> dict[str, Any]:
    metadata = dict(message.metadata or {})
    supplied_team = int(metadata.get("team_id") or 0)
    if supplied_team and supplied_team != team_id:
        raise PermissionError("请求租户与消息租户不一致")
    if message.direction != "outbound" or message.customer_id <= 0:
        raise ValueError("发送消息必须关联客户且方向为 outbound")
    if not message.channel_type.strip() or not message.contact_id.strip() or not message.content.strip():
        raise ValueError("发送渠道、联系人和内容不能为空")
    metadata["team_id"] = team_id
    return {
        "customer_id": message.customer_id,
        "channel_type": message.channel_type,
        "contact_id": message.contact_id,
        "contact_name": message.contact_name,
        "direction": "outbound",
        "content": message.content,
        "content_type": message.content_type,
        "metadata": metadata,
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _receipt(row: sqlite3.Row, *, replayed: bool = False) -> dict[str, Any]:
    result = json.loads(row["result_json"])
    return {
        "success": row["status"] == "accepted",
        "status": str(row["status"]),
        "request_id": str(row["request_id"]),
        "message_id": str(row["message_id"]),
        "provider_message_id": str(row["provider_message_id"]),
        "provider_state": str(row["provider_state"]),
        "persisted": bool(row["projected"]),
        "replayed": replayed,
        "dispatch_allowed": False,
        "channel_result": result,
        "error": str(result.get("error") or ("provider_delivery_failed" if row["provider_state"] == "failed" else "")),
    }


def get_delivery(idempotency_key: str, *, team_id: int = 0) -> dict[str, Any] | None:
    team_id = resolve_team_id(team_id, required=True)
    key = _request_key(idempotency_key)
    with _connect() as conn:
        # An expired sender may have reached the provider before its process
        # died. Expiry is a reconciliation state, never a new sending lease.
        conn.execute(
            "UPDATE kellai_outbound_deliveries SET status='unknown', updated_at=? "
            "WHERE team_id=? AND request_id=? AND status='sending' AND lease_until<=?",
            (_now(), team_id, key, _now()),
        )
        row = conn.execute(
            "SELECT * FROM kellai_outbound_deliveries WHERE team_id=? AND request_id=?",
            (team_id, key),
        ).fetchone()
    if row is None:
        return None
    if row["status"] == "accepted" and not row["projected"]:
        # Polling is also recovery: repair the local projection of a durable
        # acceptance without ever invoking the provider again.
        return _project_message(key, team_id=team_id, replayed=True)
    return _receipt(row, replayed=True)


def delivery_matches(
    idempotency_key: str, *, team_id: int, customer_id: int, channel_type: str,
    contact_id: str, content: str, auto_reply_inbound_id: str = "",
) -> bool:
    """Verify a worker report against the original immutable delivery intent."""

    team_id = resolve_team_id(team_id, required=True)
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM kellai_outbound_deliveries WHERE team_id=? AND request_id=?",
            (team_id, _request_key(idempotency_key)),
        ).fetchone()
    if row is None:
        return False
    payload = json.loads(row["payload_json"])
    return (
        payload["customer_id"] == int(customer_id)
        and payload["channel_type"] == channel_type
        and payload["contact_id"] == contact_id
        and payload["content"] == content
        and str(payload["metadata"].get("auto_reply_inbound_id") or "") == auto_reply_inbound_id
    )


def prepare_external(
    message: UnifiedMessage, *, idempotency_key: str, team_id: int = 0
) -> dict[str, Any]:
    """Commit a single-use permission before a native or remote sender runs."""

    team_id = resolve_team_id(team_id, required=True)
    key = _request_key(idempotency_key)
    payload = _payload(message, team_id)
    # A display-name change is not a new destination. Account/actor metadata is
    # still bound to the immutable intent; transient claim tokens belong in the
    # transport contract, not in this payload.
    semantic_payload = {k: v for k, v in payload.items() if k != "contact_name"}
    fingerprint = hashlib.sha256(_json(semantic_payload).encode()).hexdigest()
    now = _now()
    token = secrets.token_urlsafe(32)
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM kellai_outbound_deliveries WHERE team_id=? AND request_id=?",
            (team_id, key),
        ).fetchone()
        if row is not None:
            if row["payload_hash"] != fingerprint:
                raise DeliveryConflict("同一发送请求已绑定其他内容或接收人")
            receipt = _receipt(row, replayed=True)
        else:
            message_id = "delivery:" + hashlib.sha256(f"{team_id}:{key}".encode()).hexdigest()
            lease_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            conn.execute(
                "INSERT INTO kellai_outbound_deliveries "
                "(team_id, request_id, payload_hash, payload_json, channel_type, message_id, "
                "status, delivery_token, lease_until, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'sending', ?, ?, ?, ?)",
                (team_id, key, fingerprint, _json(payload), message.channel_type,
                 message_id, token, lease_until, now, now),
            )
            row = conn.execute(
                "SELECT * FROM kellai_outbound_deliveries WHERE team_id=? AND request_id=?",
                (team_id, key),
            ).fetchone()
            receipt = _receipt(row)
            receipt.update(dispatch_allowed=True, delivery_token=token)
    if receipt["replayed"] and receipt["status"] == "accepted" and not receipt["persisted"]:
        return _project_message(key, team_id=team_id, replayed=True)
    if receipt["replayed"] and receipt["status"] == "sending":
        return get_delivery(key, team_id=team_id) or receipt
    return receipt


def _project_message(key: str, *, team_id: int, replayed: bool) -> dict[str, Any]:
    from app.services.message_store import save_message

    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM kellai_outbound_deliveries WHERE team_id=? AND request_id=?",
            (team_id, key),
        ).fetchone()
    if row is None:
        raise DeliveryLeaseError("发送记录不存在")
    if row["status"] != "accepted" or row["projected"]:
        return _receipt(row, replayed=replayed)
    payload = json.loads(row["payload_json"])
    result = json.loads(row["result_json"])
    payload["metadata"] = {
        **payload["metadata"],
        **result,
        "team_id": team_id,
        "delivery_request_id": key,
        "delivery_state": str(row["provider_state"] or "accepted"),
        "provider_message_id": str(row["provider_message_id"]),
    }
    message = UnifiedMessage(id=row["message_id"], created_at=row["created_at"], **payload)
    try:
        # Recover a crash after save_message committed but before projected=1.
        # Re-applying the CRM projection could otherwise overwrite newer inbound
        # context even though the message itself has a stable primary key.
        with _connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kellai_messages'"
            ).fetchone()
            saved = conn.execute(
                "SELECT content, contact_id, channel_type, customer_id FROM kellai_messages "
                "WHERE team_id=? AND id=?", (team_id, message.id)
            ).fetchone() if exists else None
        if saved:
            if (saved["content"], saved["contact_id"], saved["channel_type"], saved["customer_id"]) != (
                message.content, message.contact_id, message.channel_type, message.customer_id
            ):
                raise DeliveryConflict("消息投影与原发送请求不一致")
        else:
            with tenant_scope(team_id):
                save_message(message)
    except Exception:
        # Acceptance is already durable. A retry can restore the same local
        # message ID without dispatching to the provider again.
        receipt = _receipt(row, replayed=replayed)
        receipt["persist_error"] = "message_persistence_pending"
        return receipt
    with _connect() as conn:
        conn.execute(
            "UPDATE kellai_outbound_deliveries SET projected=1, updated_at=? "
            "WHERE team_id=? AND request_id=? AND status IN ('accepted', 'failed')",
            (_now(), team_id, key),
        )
        row = conn.execute(
            "SELECT * FROM kellai_outbound_deliveries WHERE team_id=? AND request_id=?",
            (team_id, key),
        ).fetchone()
        # A provider callback may have arrived while save_message was running.
        # Re-read the canonical receipt before finalizing its UI projection.
        saved = conn.execute(
            "SELECT metadata_json FROM kellai_messages WHERE team_id=? AND id=?",
            (team_id, row["message_id"]),
        ).fetchone()
        if saved:
            metadata = json.loads(saved["metadata_json"] or "{}")
            metadata["delivery_state"] = str(row["provider_state"])
            conn.execute(
                "UPDATE kellai_messages SET metadata_json=? WHERE team_id=? AND id=?",
                (_json(metadata), team_id, row["message_id"]),
            )
        return _receipt(row, replayed=replayed)


def complete_external(
    *, idempotency_key: str, delivery_token: str, result: dict[str, Any], team_id: int = 0
) -> dict[str, Any]:
    """Record a result for the original attempt; never grant another send."""

    team_id = resolve_team_id(team_id, required=True)
    key = _request_key(idempotency_key)
    token = str(delivery_token or "")
    result = dict(result)
    success = result.get("success") is True
    provider_state = str(result.get("delivery_state") or ("accepted" if success else "unknown"))
    if success and provider_state not in {"accepted", "sent", "delivered", "read"}:
        raise ValueError("发送成功回执状态无效")
    # A failure is safe to retry only if the adapter explicitly established
    # that the provider did not accept it. No failure is retried implicitly.
    status = "accepted" if success else (
        "failed" if result.get("definitely_not_sent") is True else "unknown"
    )
    encoded_result = _json(result)
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM kellai_outbound_deliveries WHERE team_id=? AND request_id=?",
            (team_id, key),
        ).fetchone()
        if row is None or not token or not secrets.compare_digest(row["delivery_token"], token):
            raise DeliveryLeaseError("发送回执不属于当前任务")
        if row["status"] in {"accepted", "failed", "cancelled"}:
            if row["result_json"] != encoded_result:
                raise DeliveryConflict("发送终态已有不同回执")
            replayed = True
        else:
            if row["status"] not in {"sending", "unknown"}:
                raise DeliveryLeaseError("任务不接受发送回执")
            conn.execute(
                "UPDATE kellai_outbound_deliveries SET status=?, result_json=?, "
                "provider_message_id=?, provider_state=?, updated_at=? "
                "WHERE team_id=? AND request_id=?",
                (status, encoded_result, str(result.get("message_id") or ""),
                 provider_state, _now(), team_id, key),
            )
            replayed = False
    if status == "accepted":
        return _project_message(key, team_id=team_id, replayed=replayed)
    return get_delivery(key, team_id=team_id) or {}


async def dispatch(
    message: UnifiedMessage,
    *,
    idempotency_key: str,
    sender: Callable[[], Awaitable[dict[str, Any]]],
    team_id: int = 0,
) -> dict[str, Any]:
    """Run one provider invocation after durable reservation, then project it."""

    team_id = resolve_team_id(team_id, required=True)
    reservation = prepare_external(message, idempotency_key=idempotency_key, team_id=team_id)
    if not reservation["dispatch_allowed"]:
        return reservation
    try:
        with tenant_scope(team_id):
            result = await sender()
        if not isinstance(result, dict):
            result = {"success": False, "error": "invalid_provider_response", "delivery_state": "unknown"}
    except BaseException as exc:
        result = {"success": False, "error": "provider_result_unknown", "delivery_state": "unknown"}
        complete_external(idempotency_key=idempotency_key, delivery_token=reservation["delivery_token"],
                          result=result, team_id=team_id)
        if not isinstance(exc, Exception):
            raise
        return get_delivery(idempotency_key, team_id=team_id) or {}
    return complete_external(idempotency_key=idempotency_key, delivery_token=reservation["delivery_token"],
                             result=result, team_id=team_id)


def reconcile_receipt(
    *, team_id: int, channel_type: str, provider_message_id: str, state: str,
    provider_context: dict[str, Any] | None = None,
) -> bool:
    """Apply a verified provider webhook to its existing tenant/channel receipt."""

    team_id = resolve_team_id(team_id, required=True)
    ranks = {"accepted": 0, "sent": 1, "delivered": 2, "read": 3}
    if state not in {*ranks, "failed"} or not str(provider_message_id or ""):
        return False
    if channel_type == "chatwoot" and not {"gateway_id", "account_id", "inbox_id", "conversation_id"}.issubset(provider_context or {}):
        return False
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT * FROM kellai_outbound_deliveries WHERE team_id=? AND channel_type=? "
            "AND provider_message_id=?",
            (team_id, channel_type, str(provider_message_id)),
        ).fetchall()
        if provider_context:
            matched = []
            for candidate in rows:
                result = json.loads(candidate["result_json"])
                if all(key in result and _json(result[key]) == _json(value)
                       for key, value in provider_context.items()):
                    matched.append(candidate)
            rows = matched
        if len(rows) != 1:
            return False
        row = rows[0]
        previous = str(row["provider_state"])
        if previous == state:
            return True
        if row["status"] not in {"accepted", "unknown"}:
            return False
        if state == "failed":
            if ranks.get(previous, -1) >= ranks["delivered"]:
                return False
        elif ranks[state] < ranks.get(previous, -1):
            return False
        conn.execute(
            "UPDATE kellai_outbound_deliveries SET provider_state=?, status=?, updated_at=? "
            "WHERE team_id=? AND request_id=?",
            (state, "failed" if state == "failed" else "accepted", _now(), team_id, row["request_id"]),
        )
        # Keep the existing message API in sync when its local projection exists.
        if row["projected"]:
            saved = conn.execute(
                "SELECT metadata_json FROM kellai_messages WHERE team_id=? AND id=?",
                (team_id, row["message_id"]),
            ).fetchone()
            if saved:
                metadata = json.loads(saved["metadata_json"] or "{}")
                metadata["delivery_state"] = state
                conn.execute(
                    "UPDATE kellai_messages SET metadata_json=? WHERE team_id=? AND id=?",
                    (_json(metadata), team_id, row["message_id"]),
                )
    return True
