"""统一消息存储（SQLite · 共享 crm_store 的 kellai.db）。"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.channels.base import UnifiedMessage
from app.services.crm_store import _crm_db_path

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_messages_schema() -> None:
    """确保消息表 + 收件箱表存在（共享 kellai.db）。"""
    with sqlite3.connect(str(_crm_db_path())) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kellai_messages (
                id TEXT PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                channel_type TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                contact_name TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                content_type TEXT NOT NULL DEFAULT 'text',
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_customer ON kellai_messages(customer_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_channel ON kellai_messages(channel_type)"
        )
        # 渠道收件箱：适配器主动拉取 / webhook 入库的"待消费"消息
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kellai_channel_inbox (
                id TEXT PRIMARY KEY,
                channel_type TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                contact_name TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                content_type TEXT NOT NULL DEFAULT 'text',
                metadata_json TEXT,
                received_at TEXT NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_inbox_channel ON kellai_channel_inbox(channel_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_inbox_consumed ON kellai_channel_inbox(consumed)"
        )
        conn.commit()


@contextmanager
def _connect():
    ensure_messages_schema()
    conn = sqlite3.connect(str(_crm_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_message(msg: UnifiedMessage) -> UnifiedMessage:
    """保存一条消息到数据库。"""
    ensure_messages_schema()
    if int(msg.customer_id or 0) <= 0:
        try:
            from app.services.growth_loop import resolve_customer_for_message
            from app.services.pipeline import _customer_id_from_doc

            doc = resolve_customer_for_message(msg)
            uid = _customer_id_from_doc(doc)
            if uid > 0:
                msg = msg.model_copy(update={"customer_id": uid})
        except Exception:
            logger.warning("保存消息前解析客户失败: message_id=%s", msg.id, exc_info=True)
    is_read = 0 if str(msg.direction or "").lower() == "inbound" else 1
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO kellai_messages
                (id, customer_id, channel_type, contact_id, contact_name,
                 direction, content, content_type, metadata_json, created_at, is_read)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg.id,
                msg.customer_id,
                msg.channel_type,
                msg.contact_id,
                msg.contact_name,
                msg.direction,
                msg.content,
                msg.content_type,
                json.dumps(msg.metadata, ensure_ascii=False),
                msg.created_at,
                is_read,
            ),
        )
    try:
        from app.services.growth_loop import apply_message_to_growth_loop

        apply_message_to_growth_loop(msg)
    except Exception:
        logger.warning("消息已保存但增长闭环更新失败: message_id=%s", msg.id, exc_info=True)
    try:
        from app.services.workforce_routing import auto_assign_customer, touch_assignment

        metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
        team_id = int(metadata.get("team_id") or 0)
        if int(msg.customer_id or 0) > 0 and team_id > 0:
            if str(msg.direction or "").lower() == "inbound":
                auto_assign_customer(
                    customer_id=int(msg.customer_id),
                    team_id=team_id,
                    source=f"{msg.channel_type}_inbound",
                )
            else:
                touch_assignment(int(msg.customer_id))
    except Exception:
        logger.warning("消息已保存但接待分配更新失败: message_id=%s", msg.id, exc_info=True)
    return msg


def get_messages(
    customer_id: int,
    channel_type: str = "",
    limit: int = 50,
    since: str = "",
) -> list[UnifiedMessage]:
    """获取消息列表。"""
    ensure_messages_schema()
    with _connect() as conn:
        clauses: list[str] = ["customer_id = ?"]
        params: list[Any] = [int(customer_id)]
        if channel_type:
            clauses.append("channel_type = ?")
            params.append(channel_type)
        if since:
            clauses.append("created_at > ?")
            params.append(since)
        where = " AND ".join(clauses)
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM kellai_messages WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    messages: list[UnifiedMessage] = []
    for row in rows:
        metadata: dict = {}
        raw_meta = row["metadata_json"]
        if raw_meta:
            try:
                metadata = json.loads(raw_meta)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        messages.append(
            UnifiedMessage(
                id=row["id"],
                customer_id=row["customer_id"],
                channel_type=row["channel_type"],
                contact_id=row["contact_id"],
                contact_name=row["contact_name"],
                direction=row["direction"],
                content=row["content"],
                content_type=row["content_type"],
                metadata=metadata,
                created_at=row["created_at"],
            )
        )
    return messages


def get_messages_with_state(
    customer_id: int,
    channel_type: str = "",
    limit: int = 50,
    since: str = "",
) -> list[dict[str, Any]]:
    """获取消息列表，包含前端闭环展示需要的 read/customer/stage/intent 字段。"""
    ensure_messages_schema()
    with _connect() as conn:
        clauses: list[str] = ["customer_id = ?"]
        params: list[Any] = [int(customer_id)]
        if channel_type:
            clauses.append("channel_type = ?")
            params.append(channel_type)
        if since:
            clauses.append("created_at > ?")
            params.append(since)
        where = " AND ".join(clauses)
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM kellai_messages WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()

    try:
        from app.services.growth_loop import customer_message_context

        ctx = customer_message_context(int(customer_id))
    except Exception:
        logger.debug("获取客户消息上下文失败: customer_id=%s", customer_id, exc_info=True)
        ctx = {
            "customer_id": int(customer_id),
            "customer_name": f"客户{customer_id}",
            "stage": "",
            "stage_label": "",
            "ai_score": 0.0,
            "ai_intent": "",
            "pending_follow_up": False,
            "next_action": "",
        }
    try:
        from app.services.workforce_routing import assignment_for_customer

        assignment = assignment_for_customer(int(customer_id)) or {}
    except Exception:
        logger.debug("获取客户接待分配失败: customer_id=%s", customer_id, exc_info=True)
        assignment = {}

    result: list[dict[str, Any]] = []
    for row in rows:
        metadata: dict = {}
        raw_meta = row["metadata_json"]
        if raw_meta:
            try:
                metadata = json.loads(raw_meta)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        item = {
            "id": row["id"],
            "customer_id": int(row["customer_id"]),
            "customer_name": ctx.get("customer_name") or f"客户{customer_id}",
            "contact_id": row["contact_id"],
            "contact_name": row["contact_name"],
            "channel_type": row["channel_type"],
            "direction": row["direction"],
            "content": row["content"],
            "content_type": row["content_type"],
            "metadata": metadata,
            "read": bool(row["is_read"]),
            "created_at": row["created_at"],
            "stage": ctx.get("stage") or "",
            "stage_label": ctx.get("stage_label") or "",
            "ai_score": ctx.get("ai_score") or 0.0,
            "ai_intent": metadata.get("ai_intent") or ctx.get("ai_intent") or "",
            "pending_follow_up": bool(ctx.get("pending_follow_up")),
            "next_action": ctx.get("next_action") or "",
            "assignee_user_id": int(assignment.get("assignee_user_id") or 0),
            "assignee_name": str(assignment.get("assignee_name") or ""),
            "assignment_status": str(assignment.get("status") or "unassigned"),
            "assignment_source": str(assignment.get("source") or ""),
        }
        result.append(item)
    return result


def get_demo_customer_ids() -> set[int]:
    """Return customers created by built-in simulations or product audits.

    Mock mode only controls the frontend adapter. Simulation endpoints persist
    messages in the real SQLite store, so the business views need a durable way
    to keep those customers separate from production data. Parsing in Python
    also keeps this compatible with SQLite builds that do not include JSON1.
    """
    demo_sources = {"closed_loop_audit", "llm_full_flow"}
    customer_ids: set[int] = set()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT customer_id, metadata_json FROM kellai_messages WHERE metadata_json IS NOT NULL"
        ).fetchall()
    for row in rows:
        raw = row["metadata_json"]
        try:
            metadata = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(metadata, dict):
            continue
        simulated = metadata.get("simulated")
        is_simulated = simulated is True or simulated == 1 or str(simulated).strip().lower() in {
            "true",
            "yes",
        }
        source = str(metadata.get("source") or "").strip().lower()
        if is_simulated or source in demo_sources:
            customer_id = int(row["customer_id"] or 0)
            if customer_id > 0:
                customer_ids.add(customer_id)
    return customer_ids


def get_unread_count(customer_id: int) -> int:
    """获取单客户未读消息数量。"""
    ensure_messages_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM kellai_messages WHERE customer_id = ? AND is_read = 0 AND direction = 'inbound'",
            (int(customer_id),),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def get_unread_summary() -> dict[str, int]:
    """获取未读消息汇总。

    返回:
        {
            "total": 总未读数,
            "by_customer": { customer_id(int): unread_count(int), ... }
        }

    只统计入站消息（direction='inbound'）且未读（is_read=0）的。
    团队隔离由调用方（routes）按需过滤；此处只做统计聚合。
    """
    ensure_messages_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT customer_id, COUNT(*) AS cnt
            FROM kellai_messages
            WHERE is_read = 0 AND direction = 'inbound'
            GROUP BY customer_id
            """
        ).fetchall()
    by_customer: dict[str, int] = {}
    total = 0
    for row in rows:
        cnt = int(row["cnt"] or 0)
        if cnt <= 0:
            continue
        by_customer[str(int(row["customer_id"]))] = cnt
        total += cnt
    return {"total": total, "by_customer": by_customer}


def mark_as_read(message_ids: list[str]) -> int:
    """将消息标记为已读，返回实际更新的行数。"""
    if not message_ids:
        return 0
    ensure_messages_schema()
    with _connect() as conn:
        placeholders = ",".join("?" for _ in message_ids)
        cur = conn.execute(
            f"UPDATE kellai_messages SET is_read = 1 WHERE id IN ({placeholders}) AND is_read = 0",
            message_ids,
        )
        return int(cur.rowcount or 0)


def mark_all_as_read(customer_id: int | None = None) -> int:
    """将全部（指定客户 / 全局）入站未读消息标记为已读，返回更新的行数。"""
    ensure_messages_schema()
    with _connect() as conn:
        if customer_id is not None:
            cur = conn.execute(
                "UPDATE kellai_messages SET is_read = 1 "
                "WHERE customer_id = ? AND is_read = 0 AND direction = 'inbound'",
                (int(customer_id),),
            )
        else:
            cur = conn.execute(
                "UPDATE kellai_messages SET is_read = 1 "
                "WHERE is_read = 0 AND direction = 'inbound'"
            )
        return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# 渠道收件箱（适配器 → 后端）
# ---------------------------------------------------------------------------


def push_inbox(
    channel_type: str,
    *,
    contact_id: str,
    direction: str,
    content: str,
    contact_name: str = "",
    content_type: str = "text",
    metadata: dict | None = None,
    msg_id: str | None = None,
) -> str:
    """把一条入站消息写入收件箱（适配器 / webhook 接收方调用）。

    返回写入的 message id。
    """
    import secrets as _secrets

    ensure_messages_schema()
    mid = msg_id or f"{channel_type}:{int(time.time() * 1000)}:{_secrets.token_hex(4)}"
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO kellai_channel_inbox
                (id, channel_type, contact_id, contact_name, direction,
                 content, content_type, metadata_json, received_at, consumed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                mid,
                channel_type,
                contact_id,
                contact_name,
                direction,
                content,
                content_type,
                json.dumps(metadata or {}, ensure_ascii=False),
                _now_iso(),
            ),
        )
    return mid


def list_inbox(
    channel_type: str = "",
    *,
    limit: int = 50,
    include_consumed: bool = False,
) -> list[dict]:
    """列出收件箱消息。"""
    ensure_messages_schema()
    with _connect() as conn:
        clauses = []
        params: list[Any] = []
        if channel_type:
            clauses.append("channel_type = ?")
            params.append(channel_type)
        if not include_consumed:
            clauses.append("consumed = 0")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(int(limit))
        rows = conn.execute(
            f"SELECT * FROM kellai_channel_inbox{where} ORDER BY received_at DESC LIMIT ?",
            params,
        ).fetchall()
    result = []
    for r in rows:
        meta: dict = {}
        raw = r["metadata_json"]
        if raw:
            try:
                meta = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        result.append({
            "id": r["id"],
            "channel_type": r["channel_type"],
            "contact_id": r["contact_id"],
            "contact_name": r["contact_name"],
            "direction": r["direction"],
            "content": r["content"],
            "content_type": r["content_type"],
            "metadata": meta,
            "received_at": r["received_at"],
            "consumed": int(r["consumed"] or 0),
        })
    return result


def mark_inbox_consumed(message_ids: list[str]) -> int:
    """把收件箱消息标记为已消费。"""
    if not message_ids:
        return 0
    ensure_messages_schema()
    with _connect() as conn:
        placeholders = ",".join("?" for _ in message_ids)
        cur = conn.execute(
            f"UPDATE kellai_channel_inbox SET consumed = 1 WHERE id IN ({placeholders})",
            message_ids,
        )
        return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# 向后兼容：旧 _messages_db_path 调用方
# ---------------------------------------------------------------------------


def _messages_db_path():  # pragma: no cover - 向后兼容
    """已废弃：保留符号，所有数据统一到 kellai.db。"""
    return _crm_db_path()
