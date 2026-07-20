"""Persistent AI auto-reply queue consumed by the signed desktop app.

Inbound messages are queued exactly once.  The desktop claims jobs, uses the
native channel sender, and reports the result.  A short lease makes abandoned
jobs retryable after an app restart without polling old message history.
"""

from __future__ import annotations

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
    with sqlite3.connect(str(_crm_db_path())) as conn:
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
                PRIMARY KEY (team_id, inbound_message_id)
            )
            """
        )
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
    conn = sqlite3.connect(str(_crm_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
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


def enqueue_message(message: UnifiedMessage) -> bool:
    """Queue an eligible inbound message once. Returns True only on insert."""

    if str(message.direction or "").strip().lower() not in {"in", "inbound", "incoming", "customer"}:
        return False
    if int(message.customer_id or 0) <= 0 or not str(message.contact_id or "").strip():
        return False
    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    team_id = resolve_team_id(int(metadata.get("team_id") or 0), required=True)
    if bool(metadata.get("is_group")):
        return False
    config = _enabled_config()
    if not bool(config.get("autoReplyEnabled")):
        return False

    try:
        from app.services.pipeline import load_pipeline

        stage = str((load_pipeline(int(message.customer_id)) or {}).get("stage") or "idle")
    except Exception:
        stage = "idle"
    if not _stage_allowed(stage, list(config.get("autoReplyStages") or [])):
        return False

    now = _now()
    available_at = now + timedelta(seconds=3)
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO kellai_auto_reply_jobs
                (inbound_message_id, team_id, customer_id, channel_type,
                 contact_id, contact_name, inbound_content, content_type, stage,
                 status, available_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
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
        reply = "您好，您的消息已收到，我马上为您处理。"
    return reply[:8000], policy_reason


def claim_jobs(*, team_id: int = 0, limit: int = 3) -> list[dict[str, Any]]:
    """Lease pending jobs and attach a generated, policy-checked reply."""

    team_id = resolve_team_id(team_id, required=True)
    with tenant_scope(team_id):
        config = _enabled_config()
        if not bool(config.get("autoReplyEnabled")):
            return []
    now = _now()
    now_iso = _iso(now)
    lease_until = _iso(now + timedelta(seconds=90))
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        params: list[Any] = [now_iso, now_iso, team_id]
        params.append(max(1, min(int(limit), 10)) * 5)
        candidates = conn.execute(
            f"""
            SELECT * FROM kellai_auto_reply_jobs
            WHERE attempts < 20
              AND (
                    (status IN ('pending', 'failed') AND available_at <= ?)
                 OR (status = 'processing' AND lease_until != '' AND lease_until <= ?)
              )
              AND team_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            params,
        ).fetchall()

        # Coalesce bursts from one contact: answer the latest inbound message.
        latest_by_contact: dict[tuple[int, str, str], sqlite3.Row] = {}
        for row in candidates:
            key = (
                int(row["team_id"]),
                str(row["channel_type"]),
                str(row["contact_id"]),
            )
            previous = latest_by_contact.get(key)
            if previous is None or str(row["created_at"]) >= str(previous["created_at"]):
                latest_by_contact[key] = row
        selected = list(latest_by_contact.values())[: max(1, min(int(limit), 10))]
        selected_ids = {str(row["inbound_message_id"]) for row in selected}
        for row in candidates:
            inbound_id = str(row["inbound_message_id"])
            key = (
                int(row["team_id"]),
                str(row["channel_type"]),
                str(row["contact_id"]),
            )
            latest = latest_by_contact.get(key)
            if latest is not None and inbound_id != str(latest["inbound_message_id"]):
                conn.execute(
                    "UPDATE kellai_auto_reply_jobs SET status='superseded', updated_at=? "
                    "WHERE team_id=? AND inbound_message_id=?",
                    (now_iso, team_id, inbound_id),
                )
        for inbound_id in selected_ids:
            conn.execute(
                """
                UPDATE kellai_auto_reply_jobs
                SET status='processing', attempts=attempts+1, lease_until=?,
                    last_error='', updated_at=?
                WHERE team_id=? AND inbound_message_id=?
                """,
                (lease_until, now_iso, team_id, inbound_id),
            )

    jobs: list[dict[str, Any]] = []
    for selected_row in selected:
        inbound_id = str(selected_row["inbound_message_id"])
        try:
            reply, policy_reason = _build_reply(selected_row)
        except Exception as exc:
            reply = "您好，您的消息已收到，我马上为您处理。"
            policy_reason = f"AI 生成异常，已使用安全兜底：{str(exc)[:200]}"
        with _connect() as conn:
            conn.execute(
                """
                UPDATE kellai_auto_reply_jobs
                SET reply_content=?, policy_reason=?, updated_at=?
                WHERE team_id=? AND inbound_message_id=? AND status='processing'
                """,
                (reply, policy_reason, _iso(), team_id, inbound_id),
            )
        jobs.append(
            {
                "inbound_message_id": inbound_id,
                "team_id": int(selected_row["team_id"] or 0),
                "customer_id": int(selected_row["customer_id"]),
                "channel_type": str(selected_row["channel_type"]),
                "contact_id": str(selected_row["contact_id"]),
                "contact_name": str(selected_row["contact_name"]),
                "inbound_content": str(selected_row["inbound_content"]),
                "reply_content": reply,
                "policy_reason": policy_reason,
                "attempt": int(selected_row["attempts"] or 0) + 1,
            }
        )
    return jobs


def complete_job(
    inbound_message_id: str,
    *,
    success: bool,
    error: str = "",
    outbound_message_id: str = "",
    team_id: int = 0,
) -> bool:
    inbound_id = str(inbound_message_id or "").strip()
    if not inbound_id:
        return False
    try:
        team_id = resolve_team_id(team_id, required=True)
    except PermissionError:
        return False
    now = _now()
    with _connect() as conn:
        if success:
            params: list[Any] = [
                str(outbound_message_id or ""),
                _iso(now),
                _iso(now),
                team_id,
                inbound_id,
            ]
            cursor = conn.execute(
                f"""
                UPDATE kellai_auto_reply_jobs
                SET status='sent', outbound_message_id=?, sent_at=?, lease_until='',
                    last_error='', updated_at=?
                WHERE team_id=? AND inbound_message_id=? AND status != 'sent'
                """,
                params,
            )
        else:
            row = conn.execute(
                "SELECT attempts FROM kellai_auto_reply_jobs "
                "WHERE team_id=? AND inbound_message_id=?",
                (team_id, inbound_id),
            ).fetchone()
            if row is None:
                return False
            attempts = int(row["attempts"] or 1) if row else 1
            delay = min(300, max(10, 5 * (2 ** min(attempts, 6))))
            update_params: list[Any] = [
                _iso(now + timedelta(seconds=delay)),
                str(error or "发送失败")[:1000],
                _iso(now),
                team_id,
                inbound_id,
            ]
            cursor = conn.execute(
                f"""
                UPDATE kellai_auto_reply_jobs
                SET status='failed', available_at=?, lease_until='', last_error=?, updated_at=?
                WHERE team_id=? AND inbound_message_id=? AND status != 'sent'
                """,
                update_params,
            )
        return int(cursor.rowcount or 0) > 0


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
        "stages": list(config.get("autoReplyStages") or []),
        "counts": counts,
        "latest": latest_payload,
    }


__all__ = [
    "SAFE_CONFIRMATION_REPLY",
    "claim_jobs",
    "complete_job",
    "enqueue_message",
    "ensure_schema",
    "runtime_status",
]
