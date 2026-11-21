"""Persistent AI auto-reply queue shared by API and signed desktop workers.

Inbound messages are queued once. Leased drafting may be retried; once sending
starts, recovery consults the durable delivery receipt and never resends an
unknown external side effect. Every worker result is fenced by its lease token.

Only persisted, non-demo, real-time text can start an automatic reply. The
15-minute window is measured from the provider timestamp (or the original
message timestamp when no provider timestamp exists), never from queue/retry
time. Draft generation may retry within that window. History backfills never
start replies; already-sending/unknown work remains eligible for receipt
reconciliation after the window, but never for another external send.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from app.channels.base import UnifiedMessage
from app.services.crm_store import _crm_db_path
from app.services.tenant_context import (
    infer_legacy_owner_team_id,
    resolve_team_id,
    tenant_scope,
)


SAFE_CONFIRMATION_REPLY = (
    "您好，您的消息已收到。涉及价格、合同、付款或交付安排，我先为您核实，"
    "确认后会尽快回复您。"
)

REALTIME_REPLY_WINDOW_SECONDS = 15 * 60
MAX_PROVIDER_CLOCK_SKEW_SECONDS = 60
_DEMO_SOURCES = {"closed_loop_audit", "llm_full_flow", "demo", "simulation", "simulated", "mock", "test"}

_STAGE_LABELS = {
    "idle": "未接触",
    "connected": "已建联",
    "intake": "需求采集",
    "intake_done": "已提交",
    "quoted": "已报价",
    "negotiating": "议价",
    "contract_pending": "待签",
    "signed": "已签",
    "delivering": "交付中",
    "delivered": "已交付",
}

_PRICE_TERMS = ("价格", "报价", "多少钱", "费用", "收费", "优惠", "折扣", "便宜", "总价")
_CONTRACT_TERMS = ("合同", "签约", "违约", "赔偿", "担保", "保证", "法律")
_DELIVERY_TERMS = ("交付", "到货", "上线时间", "完成时间", "什么时候能", "具体时间")
_PAYMENT_TERMS = ("付款", "支付", "退款", "发票", "开票", "转账", "收款")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def ensure_schema() -> None:
    with sqlite3.connect(str(_crm_db_path()), timeout=30) as conn:
        existing = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='kellai_auto_reply_jobs'"
        ).fetchone()
        if existing:
            info = conn.execute("PRAGMA table_info(kellai_auto_reply_jobs)").fetchall()
            primary_key = [
                str(row[1])
                for row in sorted(info, key=lambda item: int(item[5]))
                if int(row[5]) > 0
            ]
            if primary_key != ["team_id", "inbound_message_id"]:
                conn.execute(
                    "ALTER TABLE kellai_auto_reply_jobs "
                    "RENAME TO kellai_auto_reply_jobs_legacy_tenant"
                )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kellai_auto_reply_jobs (
                team_id INTEGER NOT NULL DEFAULT 0,
                inbound_message_id TEXT NOT NULL,
                customer_id INTEGER NOT NULL,
                channel_type TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                contact_name TEXT NOT NULL DEFAULT '',
                inbound_content TEXT NOT NULL DEFAULT '',
                content_type TEXT NOT NULL DEFAULT 'text',
                stage TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                reply_content TEXT NOT NULL DEFAULT '',
                policy_reason TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                available_at TEXT NOT NULL,
                lease_until TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                outbound_message_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT '',
                lease_token TEXT NOT NULL DEFAULT '',
                delivery_key TEXT NOT NULL DEFAULT '',
                inbound_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (team_id, inbound_message_id)
            )
            """
        )
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(kellai_auto_reply_jobs)")}
        for name in ("lease_token", "delivery_key", "inbound_at"):
            if name not in columns:
                conn.execute(f"ALTER TABLE kellai_auto_reply_jobs ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        legacy = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='kellai_auto_reply_jobs_legacy_tenant'"
        ).fetchone()
        if legacy:
            owner_team_id = infer_legacy_owner_team_id()
            conn.execute(
                f"""
                INSERT OR IGNORE INTO kellai_auto_reply_jobs
                    (team_id, inbound_message_id, customer_id, channel_type,
                     contact_id, contact_name, inbound_content, content_type,
                     stage, status, reply_content, policy_reason, attempts,
                     available_at, lease_until, last_error, outbound_message_id,
                     created_at, updated_at, sent_at)
                SELECT CASE WHEN team_id > 0 THEN team_id ELSE {int(owner_team_id or 0)} END,
                       inbound_message_id, customer_id, channel_type, contact_id,
                       contact_name, inbound_content, content_type, stage, status,
                       reply_content, policy_reason, attempts, available_at,
                       lease_until, last_error, outbound_message_id, created_at,
                       updated_at, sent_at
                FROM kellai_auto_reply_jobs_legacy_tenant
                """
            )
            conn.execute("DROP TABLE kellai_auto_reply_jobs_legacy_tenant")
        if ("inbound_at" not in columns or legacy) and conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kellai_messages'"
        ).fetchone():
            # Upgrade a still-fresh pending retry from its persisted original
            # message, never from the job's last retry/update timestamp.
            for team_id, inbound_id, created_at, raw_metadata in conn.execute(
                "SELECT job.team_id, job.inbound_message_id, message.created_at, message.metadata_json "
                "FROM kellai_auto_reply_jobs AS job JOIN kellai_messages AS message "
                "ON message.team_id=job.team_id AND message.id=job.inbound_message_id "
                "WHERE job.inbound_at=''"
            ).fetchall():
                metadata = _metadata(raw_metadata)
                source_at = _source_timestamp(created_at, metadata)
                if source_at is not None and not _non_live_reason(metadata):
                    conn.execute(
                        "UPDATE kellai_auto_reply_jobs SET inbound_at=? WHERE team_id=? AND inbound_message_id=?",
                        (_iso(source_at), team_id, inbound_id),
                    )
        # Legacy processing included native sending. Its lease expiry does not
        # establish that a message was unsent, so preserve it for reconciliation.
        conn.execute(
            "UPDATE kellai_auto_reply_jobs SET status='unknown' "
            "WHERE status='processing' AND lease_token=''"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auto_reply_team_status "
            "ON kellai_auto_reply_jobs(team_id, status, available_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auto_reply_team_contact "
            "ON kellai_auto_reply_jobs(team_id, channel_type, contact_id, created_at)"
        )
        conn.commit()


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


def _enabled_config() -> dict[str, Any]:
    from app.services.llm_config import public_config

    return public_config()


def _stage_allowed(stage: str, configured: list[Any]) -> bool:
    values = {str(item or "").strip() for item in configured if str(item or "").strip()}
    if not values:
        return True
    label = _STAGE_LABELS.get(stage, "")
    aliases = {stage, label}
    if stage == "negotiating":
        aliases.add("谈判中")
    if stage == "signed":
        aliases.add("成交")
    return bool(values.intersection(aliases))


def _flag(value: Any) -> bool:
    # Treat malformed nonempty flags as restricted, while accepting common
    # serialized false values from older adapters.
    return str(value).strip().lower() not in {"", "0", "false", "no", "off", "none"} if value is not None else False


def _metadata(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _demo_metadata(metadata: dict[str, Any]) -> bool:
    return (any(_flag(metadata.get(key)) for key in ("simulated", "is_demo", "demo", "is_simulated"))
            or str(metadata.get("source") or "").strip().lower() in _DEMO_SOURCES)


def _non_live_reason(metadata: dict[str, Any]) -> str:
    if _demo_metadata(metadata):
        return "simulation_or_demo_message"
    if any(_flag(metadata.get(key)) for key in ("historical", "is_history", "history_backfill", "backfill")):
        return "historical_message"
    if _flag(metadata.get("is_group")):
        return "group_message"
    return ""


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool) or not str(value).strip():
        return None
    try:
        if isinstance(value, (int, float)) or str(value).replace(".", "", 1).isdigit():
            number = float(value)
            if number > 10_000_000_000:
                number /= 1000
            return datetime.fromtimestamp(number, tz=timezone.utc)
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _source_timestamp(created_at: Any, metadata: dict[str, Any]) -> datetime | None:
    # An explicitly missing/invalid provider time must not turn into "now".
    return _parse_timestamp(metadata.get("provider_created_at") if "provider_created_at" in metadata else created_at)


def _fresh(source_at: datetime | None, now: datetime | None = None) -> bool:
    if source_at is None:
        return False
    age = ((now or _now()) - source_at).total_seconds()
    return -MAX_PROVIDER_CLOCK_SKEW_SECONDS <= age <= REALTIME_REPLY_WINDOW_SECONDS


def _current_customer(customer_id: int, team_id: int) -> dict[str, Any] | None:
    # load_pipeline creates a missing customer; authorization must only read.
    from app.services.pipeline import _pipeline_file, _read_pipeline_file, normalize_stage_id

    with tenant_scope(team_id):
        doc = _read_pipeline_file(_pipeline_file(customer_id))
    if not doc or int(doc.get("team_id") or 0) != team_id or int(doc.get("customer_id") or doc.get("market_user_id") or 0) != customer_id:
        return None
    doc["stage"] = normalize_stage_id(str(doc.get("stage") or "idle"))
    return doc


def _customer_is_demo(doc: dict[str, Any]) -> bool:
    from app.services.pipeline import _is_demo_pipeline

    return _demo_metadata(doc) or _is_demo_pipeline(doc, set())


def _stored_message(conn: sqlite3.Connection, team_id: int, inbound_id: str) -> sqlite3.Row | None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kellai_messages'").fetchone():
        return None
    return conn.execute(
        "SELECT rowid AS message_order, * FROM kellai_messages WHERE team_id=? AND id=?",
        (team_id, inbound_id),
    ).fetchone()


def _draft_rejection(conn: sqlite3.Connection, row: Any, config: dict[str, Any], *, same_stage: bool = False) -> tuple[str, str]:
    """Read current message/customer state on the same SQLite transaction."""
    team_id, customer_id = int(row["team_id"]), int(row["customer_id"])
    message = _stored_message(conn, team_id, str(row["inbound_message_id"]))
    if message is None:
        return "original_message_missing", ""
    metadata = _metadata(message["metadata_json"])
    if (_non_live_reason(metadata) or message["content_type"] != "text"
            or str(message["direction"]).lower() not in {"inbound", "in", "incoming", "customer"}):
        return _non_live_reason(metadata) or "unsupported_message", ""
    if (int(message["customer_id"]), message["channel_type"], message["contact_id"], message["content"]) != (
        customer_id, row["channel_type"], row["contact_id"], row["inbound_content"]
    ):
        return "original_message_changed", ""
    source_at = _source_timestamp(message["created_at"], metadata)
    if not _fresh(source_at) or not _fresh(_parse_timestamp(row["inbound_at"])):
        return "realtime_window_expired", ""
    if source_at != _parse_timestamp(row["inbound_at"]):
        return "original_timestamp_changed", ""
    customer = _current_customer(customer_id, team_id)
    if customer is None:
        return "customer_missing", ""
    if _customer_is_demo(customer):
        return "demo_customer", ""
    stage = str(customer["stage"])
    if not _stage_allowed(stage, list(config.get("autoReplyStages") or [])):
        return "customer_stage_not_enabled", stage
    if same_stage and stage != row["stage"]:
        return "customer_stage_changed", stage
    # Legacy simulations may have persisted only a message marker.
    for other in conn.execute("SELECT metadata_json FROM kellai_messages WHERE team_id=? AND customer_id=?", (team_id, customer_id)):
        if _demo_metadata(_metadata(other["metadata_json"])):
            return "demo_customer", stage
    for other in conn.execute(
        "SELECT rowid AS message_order, * FROM kellai_messages WHERE team_id=? AND channel_type=? AND contact_id=? AND id!=?",
        (team_id, row["channel_type"], row["contact_id"], row["inbound_message_id"]),
    ):
        direction = str(other["direction"]).lower()
        if direction not in {"inbound", "in", "incoming", "customer", "outbound", "out", "outgoing"}:
            continue
        other_at = _source_timestamp(other["created_at"], _metadata(other["metadata_json"]))
        newer = (other_at is not None and (other_at > source_at or (other_at == source_at and other["message_order"] > message["message_order"])))
        if other_at is None and other["message_order"] > message["message_order"]:
            newer = True
        if newer:
            return ("newer_outbound_exists" if direction in {"outbound", "out", "outgoing"} else "newer_inbound_exists"), stage
    return "", stage


def _retire_draft(conn: sqlite3.Connection, row: Any, reason: str) -> None:
    status = "expired" if reason == "realtime_window_expired" else (
        "superseded" if reason in {"newer_inbound_exists", "newer_outbound_exists"} else "cancelled")
    conn.execute(
        "UPDATE kellai_auto_reply_jobs SET status=?, last_error=?, lease_token='', lease_until='', updated_at=? "
        "WHERE team_id=? AND inbound_message_id=? AND status IN ('pending','failed','processing')",
        (status, reason, _iso(), row["team_id"], row["inbound_message_id"]),
    )


def enqueue_message(message: UnifiedMessage) -> bool:
    """Queue an eligible inbound message once. Returns True only on insert."""

    if str(message.direction or "").strip().lower() not in {"in", "inbound", "incoming", "customer"}:
        return False
    if int(message.customer_id or 0) <= 0 or not str(message.contact_id or "").strip():
        return False
    # The current reply generator receives text only. Keep media and events in
    # the inbox without inventing a reply to content the model never parsed.
    if message.content_type != "text" or not str(message.content or "").strip():
        return False
    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    team_id = resolve_team_id(int(metadata.get("team_id") or 0), required=True)
    if _non_live_reason(metadata):
        return False
    source_at = _source_timestamp(message.created_at, metadata)
    if not _fresh(source_at):
        return False
    with tenant_scope(team_id):
        config = _enabled_config()
        if not bool(config.get("autoReplyEnabled")):
            return False
        customer = _current_customer(int(message.customer_id), team_id)
        if customer is None or _customer_is_demo(customer):
            return False
        stage = str(customer["stage"])
    if not _stage_allowed(stage, list(config.get("autoReplyStages") or [])):
        return False

    now = _now()
    available_at = now + timedelta(seconds=3)
    with _connect() as conn:
        persisted = _stored_message(conn, team_id, str(message.id))
        if persisted is None:
            return False
        persisted_metadata = _metadata(persisted["metadata_json"])
        if _non_live_reason(persisted_metadata):
            return False
        if (int(persisted["customer_id"]), persisted["channel_type"], persisted["contact_id"], persisted["content"], persisted["direction"], persisted["content_type"]) != (
            int(message.customer_id), message.channel_type, message.contact_id, message.content, message.direction, message.content_type
        ):
            return False
        source_at = _source_timestamp(persisted["created_at"], persisted_metadata)
        if not _fresh(source_at, now):
            return False
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO kellai_auto_reply_jobs
                (inbound_message_id, team_id, customer_id, channel_type,
                 contact_id, contact_name, inbound_content, content_type, stage,
                 status, available_at, created_at, updated_at, inbound_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                str(message.id),
                team_id,
                int(message.customer_id),
                str(message.channel_type or ""),
                str(message.contact_id or ""),
                str(message.contact_name or ""),
                str(message.content or ""),
                str(message.content_type or "text"),
                stage,
                _iso(available_at),
                _iso(now),
                _iso(now),
                _iso(source_at),
            ),
        )
        return int(cursor.rowcount or 0) > 0


def _requires_safe_reply(content: str, configured_scenarios: list[Any]) -> str:
    text = str(content or "")
    scenarios = {str(item or "").strip() for item in configured_scenarios}
    checks: list[tuple[str, tuple[str, ...], bool]] = [
        ("涉及价格", _PRICE_TERMS, "涉及价格" in scenarios),
        ("合同条款", _CONTRACT_TERMS, "合同条款" in scenarios),
        ("交付时间", _DELIVERY_TERMS, "交付时间" in scenarios),
        ("付款与退款", _PAYMENT_TERMS, True),
    ]
    for label, terms, enabled in checks:
        if enabled and any(term in text for term in terms):
            return label
    return ""


def _build_reply(row: sqlite3.Row) -> tuple[str, str]:
    from app.services.ai_copilot import generate_auto_reply
    from app.services.message_store import get_messages

    team_id = int(row["team_id"] or 0)
    with tenant_scope(team_id):
        config = _enabled_config()
        history_messages = get_messages(
            int(row["customer_id"]), limit=8, team_id=team_id
        )
        history = [
            f"{'客服' if str(item.direction) == 'outbound' else '客户'}：{item.content}"
            for item in reversed(history_messages)
        ]
        result = generate_auto_reply(
            int(row["customer_id"]),
            message=str(row["inbound_content"] or ""),
            stage=str(row["stage"] or ""),
            history=history,
        )
    if result.get("generation_source") != "llm":
        raise ValueError("automatic_reply_requires_verified_model_output")
    policy_reason = _requires_safe_reply(
        str(row["inbound_content"] or ""),
        list(config.get("confirmScenarios") or []),
    )
    if not bool(result.get("can_auto_send", True)):
        policy_reason = str(result.get("reason") or policy_reason or "AI 安全策略")
    reply = str(result.get("draft") or "").strip()
    if policy_reason:
        reply = SAFE_CONFIRMATION_REPLY
    if not reply:
        raise ValueError("automatic_reply_model_output_empty")
    return reply[:8000], policy_reason


def claim_jobs(
    *, team_id: int = 0, limit: int = 3, channel_types: list[str] | None = None,
    transport: str | None = None,
) -> list[dict[str, Any]]:
    """Lease the latest live message per conversation, then apply worker limit.

    ``transport`` selects api/desktop before a lease or model call is made.
    Resolver reads run outside the write transaction; current queue, customer
    and message state are checked again inside the transaction that grants it.
    """

    team_id = resolve_team_id(team_id, required=True)
    if transport not in {None, "api", "desktop"}:
        raise ValueError("unsupported_auto_reply_transport")
    _reconcile_jobs(team_id)
    channels = None if channel_types is None else sorted({str(value).strip() for value in channel_types if str(value).strip()})
    if channels == []:
        return []
    with tenant_scope(team_id):
        config = _enabled_config()
        if not bool(config.get("autoReplyEnabled")):
            return []
    limit = max(1, min(int(limit), 10))
    channel_clause = "" if channels is None else " AND job.channel_type IN (" + ",".join("?" for _ in channels) + ")"
    now_iso = _iso()
    params: list[Any] = [team_id, now_iso, now_iso, now_iso]
    params.extend(channels or [])
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE kellai_auto_reply_jobs SET status='unknown', updated_at=? "
            "WHERE team_id=? AND status='sending' AND lease_until<=?",
            (now_iso, team_id, now_iso),
        )
        conn.execute(
            "UPDATE kellai_auto_reply_jobs SET status='expired', last_error='realtime_window_expired', "
            "lease_token='', lease_until='', updated_at=? WHERE team_id=? "
            "AND status IN ('pending','failed','processing') AND (inbound_at='' OR inbound_at<?)",
            (now_iso, team_id, _iso(_now() - timedelta(seconds=REALTIME_REPLY_WINDOW_SECONDS))),
        )
        # Supersede against the entire queue, including messages still inside
        # the debounce window. LIMIT before this step can answer old messages.
        conn.execute(
            """UPDATE kellai_auto_reply_jobs AS older SET status='superseded',
               last_error='newer_inbound_exists', lease_token='', lease_until='', updated_at=?
               WHERE team_id=? AND status IN ('pending','failed','processing')
               AND EXISTS (SELECT 1 FROM kellai_auto_reply_jobs AS newer
                   WHERE newer.team_id=older.team_id AND newer.channel_type=older.channel_type
                     AND newer.contact_id=older.contact_id
                     AND (newer.inbound_at>older.inbound_at OR
                          (newer.inbound_at=older.inbound_at AND newer.rowid>older.rowid)))""",
            (now_iso, team_id),
        )
        candidates = conn.execute(
            f"""
            SELECT * FROM kellai_auto_reply_jobs AS job
            WHERE team_id=? AND attempts < 20
              AND ((status IN ('pending', 'failed') AND available_at<=?)
                   OR (status='processing' AND lease_until<=?))
              AND NOT EXISTS (
                  SELECT 1 FROM kellai_auto_reply_jobs AS active
                  WHERE active.team_id=job.team_id
                    AND active.channel_type=job.channel_type
                    AND active.contact_id=job.contact_id
                    AND active.inbound_message_id!=job.inbound_message_id
                    AND (active.status IN ('sending', 'unknown', 'awaiting_persistence')
                         OR (active.status='processing' AND active.lease_until>?))
              )
              {channel_clause}
            ORDER BY job.created_at ASC, job.rowid ASC
            """,
            params,
        ).fetchall()

    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        if len(selected) >= limit:
            break
        if transport is not None:
            from app.channels.capabilities import resolve_send_capability

            with _connect() as conn:
                persisted = _stored_message(conn, team_id, str(candidate["inbound_message_id"]))
            with tenant_scope(team_id):
                capability = resolve_send_capability(
                    str(candidate["channel_type"]), contact_id=str(candidate["contact_id"]),
                    customer_id=int(candidate["customer_id"]), contact_name=str(candidate["contact_name"]),
                    metadata=_metadata(persisted["metadata_json"]) if persisted else {}, team_id=team_id,
                )
            if capability.get("transport") != transport:
                continue
            if transport == "api" and not (capability.get("send") and capability.get("auto_reply")):
                continue
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now_iso = _iso()
            row = conn.execute(
                "SELECT * FROM kellai_auto_reply_jobs WHERE team_id=? AND inbound_message_id=? "
                "AND attempts<20 AND ((status IN ('pending','failed') AND available_at<=?) "
                "OR (status='processing' AND lease_until<=?))",
                (team_id, candidate["inbound_message_id"], now_iso, now_iso),
            ).fetchone()
            if row is None:
                continue
            if conn.execute(
                "SELECT 1 FROM kellai_auto_reply_jobs WHERE team_id=? AND channel_type=? AND contact_id=? "
                "AND inbound_message_id!=? AND (status IN ('sending','unknown','awaiting_persistence') "
                "OR (status='processing' AND lease_until>?)) LIMIT 1",
                (team_id, row["channel_type"], row["contact_id"], row["inbound_message_id"], now_iso),
            ).fetchone():
                continue
            reason, stage = _draft_rejection(conn, row, config)
            if reason:
                _retire_draft(conn, row, reason)
                continue
            token = secrets.token_urlsafe(32)
            lease_until = _iso(_now() + timedelta(seconds=90))
            conn.execute(
                "UPDATE kellai_auto_reply_jobs SET status='processing', attempts=attempts+1, stage=?, "
                "lease_until=?, lease_token=?, delivery_key=?, last_error='', updated_at=? "
                "WHERE team_id=? AND inbound_message_id=?",
                (stage, lease_until, token, f"auto:{row['inbound_message_id']}", now_iso, team_id, row["inbound_message_id"]),
            )
            selected.append({**dict(row), "stage": stage, "lease_token": token, "lease_until": lease_until})

    jobs: list[dict[str, Any]] = []
    for row in selected:
        inbound_id = str(row["inbound_message_id"])
        token = row["lease_token"]
        try:
            reply, policy_reason = _build_reply(row)
        except Exception:
            complete_job(inbound_id, success=False, error="reply_generation_failed",
                         lease_token=token, team_id=team_id)
            continue
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT * FROM kellai_auto_reply_jobs WHERE team_id=? AND inbound_message_id=? "
                "AND status='processing' AND lease_token=? AND lease_until>?",
                (team_id, inbound_id, token, _iso()),
            ).fetchone()
            if current is None:
                continue
            reason, _ = _draft_rejection(conn, current, config, same_stage=True)
            if reason:
                _retire_draft(conn, current, reason)
                continue
            changed = conn.execute(
                "UPDATE kellai_auto_reply_jobs SET reply_content=?, policy_reason=?, updated_at=? "
                "WHERE team_id=? AND inbound_message_id=? AND status='processing' "
                "AND lease_token=? AND lease_until>?",
                (reply, policy_reason, _iso(), team_id, inbound_id, token, _iso()),
            ).rowcount
        if not changed:
            continue
        jobs.append({
            "inbound_message_id": inbound_id,
            "team_id": team_id,
            "customer_id": int(row["customer_id"]),
            "channel_type": str(row["channel_type"]),
            "contact_id": str(row["contact_id"]),
            "contact_name": str(row["contact_name"]),
            "inbound_content": str(row["inbound_content"]),
            "reply_content": reply,
            "policy_reason": policy_reason,
            "generation_source": "policy" if policy_reason else "llm",
            "attempt": int(row["attempts"]) + 1,
            "lease_token": token,
            "lease_until": row["lease_until"],
            "delivery_key": f"auto:{inbound_id}",
        })
    return jobs


def begin_delivery(
    inbound_message_id: str, *, lease_token: str, team_id: int = 0,
    customer_id: int, channel_type: str, contact_id: str, content: str,
) -> bool:
    """Fence a worker and freeze its approved reply before granting a send."""

    team_id = resolve_team_id(team_id, required=True)
    with tenant_scope(team_id):
        config = _enabled_config()
        if not bool(config.get("autoReplyEnabled")):
            return False
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM kellai_auto_reply_jobs WHERE team_id=? AND inbound_message_id=?",
            (team_id, str(inbound_message_id)),
        ).fetchone()
        if row is None or not lease_token or not secrets.compare_digest(row["lease_token"], lease_token):
            return False
        if row["status"] not in {"processing", "sending"} or row["lease_until"] <= _iso():
            return False
        if (int(row["customer_id"]), row["channel_type"], row["contact_id"], row["reply_content"]) != (
            int(customer_id), str(channel_type), str(contact_id), str(content)
        ):
            return False
        reason, _ = _draft_rejection(conn, row, config, same_stage=True)
        if reason:
            # A send that already started is never reclassified as unsent.
            # Its original receipt can still complete through complete_job.
            _retire_draft(conn, row, reason)
            return False
        conn.execute(
            "UPDATE kellai_auto_reply_jobs SET status='sending', updated_at=? "
            "WHERE team_id=? AND inbound_message_id=? AND lease_token=?",
            (_iso(), team_id, str(inbound_message_id), lease_token),
        )
    return True


def _verified_delivery(row: sqlite3.Row, team_id: int) -> dict[str, Any] | None:
    from app.services import outbound_delivery

    key = str(row["delivery_key"] or "")
    if key != f"auto:{row['inbound_message_id']}":
        return None
    if not outbound_delivery.delivery_matches(
        key, team_id=team_id, customer_id=int(row["customer_id"]),
        channel_type=str(row["channel_type"]), contact_id=str(row["contact_id"]),
        content=str(row["reply_content"]), auto_reply_inbound_id=str(row["inbound_message_id"]),
    ):
        return None
    return outbound_delivery.get_delivery(key, team_id=team_id)


def complete_job(
    inbound_message_id: str, *, success: bool, error: str = "",
    outbound_message_id: str = "", team_id: int = 0,
    lease_token: str = "", delivery_key: str = "",
) -> bool:
    """Complete only the current lease and a matching durable provider receipt."""

    inbound_id = str(inbound_message_id or "").strip()
    if not inbound_id or not lease_token:
        return False
    try:
        team_id = resolve_team_id(team_id, required=True)
    except PermissionError:
        return False
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM kellai_auto_reply_jobs WHERE team_id=? AND inbound_message_id=?",
            (team_id, inbound_id),
        ).fetchone()
    if row is None or not secrets.compare_digest(row["lease_token"], lease_token):
        return False
    if delivery_key and delivery_key != row["delivery_key"]:
        return False
    if row["status"] in {"cancelled", "superseded", "expired", "dead_letter", "delivery_failed"}:
        return False
    delivery = _verified_delivery(row, team_id)
    now = _now()
    if delivery:
        if delivery["status"] == "accepted":
            if outbound_message_id and outbound_message_id != delivery["message_id"]:
                return False
            if row["status"] == "sent" and delivery["persisted"]:
                return True
            status = "sent" if delivery["persisted"] else "awaiting_persistence"
            outbound_message_id = delivery["message_id"]
            error = "" if delivery["persisted"] else "message_persistence_pending"
        elif delivery["status"] == "failed":
            status, error = "delivery_failed", delivery.get("error") or "provider_rejected"
        else:
            status, error = "unknown", "provider_result_unknown"
    else:
        # A bare success flag or arbitrary message ID is not sending evidence.
        if success or row["status"] != "processing" or row["lease_until"] <= _iso(now):
            return False
        if not _fresh(_parse_timestamp(row["inbound_at"]), now):
            status, error = "expired", "realtime_window_expired"
        else:
            status = "dead_letter" if int(row["attempts"]) >= 20 else "failed"
    delay = min(300, max(10, 5 * (2 ** min(int(row["attempts"]), 6))))
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE kellai_auto_reply_jobs SET status=?, outbound_message_id=?, sent_at=?, "
            "lease_until='', last_error=?, available_at=?, updated_at=? "
            "WHERE team_id=? AND inbound_message_id=? AND lease_token=? AND status=?",
            (status, str(outbound_message_id or ""), _iso(now) if status == "sent" else str(row["sent_at"]),
             str(error or "")[:1000], _iso(now + timedelta(seconds=delay)), _iso(now),
             team_id, inbound_id, lease_token, row["status"]),
        )
        return int(cursor.rowcount or 0) > 0


def _reconcile_jobs(team_id: int) -> None:
    """Recover lost worker reports from existing delivery receipts, without send."""

    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM kellai_auto_reply_jobs WHERE team_id=? "
            "AND status IN ('sending', 'unknown', 'awaiting_persistence') "
            "ORDER BY updated_at LIMIT 100", (team_id,),
        ).fetchall()
    for row in rows:
        delivery = _verified_delivery(row, team_id)
        if delivery and delivery["status"] in {"accepted", "failed"}:
            complete_job(str(row["inbound_message_id"]), success=delivery["success"],
                         lease_token=str(row["lease_token"]), team_id=team_id)


def cancel_job(inbound_message_id: str, *, team_id: int = 0) -> bool:
    """Cancel unsent drafting work, invalidating any outstanding draft worker."""

    team_id = resolve_team_id(team_id, required=True)
    with _connect() as conn:
        changed = conn.execute(
            "UPDATE kellai_auto_reply_jobs SET status='cancelled', lease_token='', "
            "lease_until='', updated_at=? WHERE team_id=? AND inbound_message_id=? "
            "AND status IN ('pending', 'failed', 'processing')",
            (_iso(), team_id, str(inbound_message_id)),
        ).rowcount
        return bool(changed)


def runtime_status(*, team_id: int = 0) -> dict[str, Any]:
    team_id = resolve_team_id(team_id, required=True)
    with tenant_scope(team_id):
        config = _enabled_config()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM kellai_auto_reply_jobs "
            "WHERE team_id = ? GROUP BY status",
            (team_id,),
        ).fetchall()
        latest = conn.execute(
            "SELECT * FROM kellai_auto_reply_jobs WHERE team_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (team_id,),
        ).fetchone()
    counts = {str(row["status"]): int(row["count"] or 0) for row in rows}
    latest_payload: dict[str, Any] = {}
    if latest is not None:
        latest_payload = {
            "inbound_message_id": str(latest["inbound_message_id"]),
            "contact_name": str(latest["contact_name"]),
            "channel_type": str(latest["channel_type"]),
            "status": str(latest["status"]),
            "last_error": str(latest["last_error"]),
            "updated_at": str(latest["updated_at"]),
            "sent_at": str(latest["sent_at"]),
            "policy_reason": str(latest["policy_reason"]),
        }
    return {
        "enabled": bool(config.get("autoReplyEnabled")),
        "realtime_window_seconds": REALTIME_REPLY_WINDOW_SECONDS,
        "stages": list(config.get("autoReplyStages") or []),
        "counts": counts,
        "latest": latest_payload,
    }


__all__ = [
    "SAFE_CONFIRMATION_REPLY",
    "REALTIME_REPLY_WINDOW_SECONDS",
    "begin_delivery",
    "cancel_job",
    "claim_jobs",
    "complete_job",
    "enqueue_message",
    "ensure_schema",
    "runtime_status",
]
