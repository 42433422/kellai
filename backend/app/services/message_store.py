"""Durable channel inbox, messages and transport contacts; no CRM projections."""
from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.channels.base import UnifiedMessage
from app.services.storage import database_path
from app.services.tenant_context import resolve_team_id, infer_legacy_owner_team_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connection_id(value: str = "", *, metadata: dict | None = None, required: bool = True) -> str:
    from app.channels.config_store import current_connection_id
    contextual = current_connection_id()
    supplied = value or str((metadata or {}).get("connection_id") or "")
    if contextual and supplied and contextual != supplied:
        raise PermissionError("消息账号与当前连接不一致")
    resolved = supplied or contextual
    if required and not resolved:
        raise ValueError("缺少明确的 connection_id")
    return resolved


def _effective_team_id(explicit_team_id: int | None = None, *, metadata: dict | None = None) -> int:
    value = int((metadata or {}).get("team_id") or 0)
    if explicit_team_id and value and int(explicit_team_id) != value:
        raise PermissionError("消息工作区不一致")
    return resolve_team_id(explicit_team_id or value, required=True)


def ensure_messages_schema() -> None:
    with sqlite3.connect(str(database_path()), timeout=30) as conn:
        conn.execute("BEGIN IMMEDIATE")
        legacy_owner = None
        for table in ("kellai_messages", "kellai_channel_inbox"):
            info = conn.execute(f"PRAGMA table_info({table})").fetchall()
            if info and [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]] != ["team_id", "connection_id", "id"]:
                if legacy_owner is None:
                    legacy_owner = infer_legacy_owner_team_id()
                conn.execute(f"ALTER TABLE {table} RENAME TO {table}_before_connections")
        conn.execute("""CREATE TABLE IF NOT EXISTS kellai_messages (
            team_id INTEGER NOT NULL, connection_id TEXT NOT NULL DEFAULT '', id TEXT NOT NULL,
            customer_id INTEGER NOT NULL, channel_type TEXT NOT NULL, contact_id TEXT NOT NULL,
            contact_name TEXT NOT NULL DEFAULT '', direction TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
            content_type TEXT NOT NULL DEFAULT 'text', metadata_json TEXT, created_at TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(team_id,connection_id,id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS kellai_channel_inbox (
            team_id INTEGER NOT NULL, connection_id TEXT NOT NULL DEFAULT '', id TEXT NOT NULL,
            channel_type TEXT NOT NULL, contact_id TEXT NOT NULL, contact_name TEXT NOT NULL DEFAULT '',
            direction TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', content_type TEXT NOT NULL DEFAULT 'text',
            metadata_json TEXT, received_at TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(team_id,connection_id,id)
        )""")
        for table in ("kellai_messages", "kellai_channel_inbox"):
            legacy = table + "_before_connections"
            info = conn.execute(f"PRAGMA table_info({legacy})").fetchall()
            if not info:
                continue
            cols = [r[1] for r in info]
            common = [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[1] in cols]
            inserted_cols = list(common)
            expressions = list(common)
            if legacy_owner is None:
                legacy_owner = infer_legacy_owner_team_id()
            metadata_team = ("CASE WHEN json_valid(metadata_json) THEN "
                             "CAST(json_extract(metadata_json,'$.team_id') AS INTEGER) ELSE 0 END"
                             if "metadata_json" in cols else "0")
            attribution = f"CASE WHEN ({metadata_team})>0 THEN ({metadata_team}) ELSE {legacy_owner} END"
            if "team_id" not in common:
                inserted_cols.append("team_id")
                expressions.append(attribution)
            else:
                expressions[common.index("team_id")] = f"CASE WHEN team_id>0 THEN team_id ELSE ({attribution}) END"
            if "connection_id" not in common:
                inserted_cols.append("connection_id")
                expressions.append("''")
            conn.execute(f"INSERT INTO {table} ({','.join(inserted_cols)}) SELECT {','.join(expressions)} FROM {legacy}")
            # Same transaction, checked by SQLite uniqueness constraints: all
            # original rows are preserved before the superseded table is removed.
            conn.execute(f"DROP TABLE {legacy}")
        conn.execute("""CREATE TABLE IF NOT EXISTS kellai_transport_contacts (
            team_id INTEGER NOT NULL, connection_id TEXT NOT NULL, channel_type TEXT NOT NULL,
            contact_id TEXT NOT NULL, customer_id INTEGER NOT NULL, contact_name TEXT NOT NULL,
            last_message_at TEXT NOT NULL DEFAULT '', is_demo INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(team_id,connection_id,channel_type,contact_id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_messages_contact ON kellai_messages(team_id,connection_id,customer_id,created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_inbox_pending ON kellai_channel_inbox(team_id,connection_id,consumed,received_at)")


@contextmanager
def _connect():
    ensure_messages_schema()
    conn = sqlite3.connect(str(database_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate_account_bindings() -> int:
    """Bind the former single-channel slot only to its imported legacy account.

    Rows for deleted/missing configurations stay unassigned; a newly created
    account never inherits history or a pending delivery from an unknown one.
    """
    from app.channels.config_store import list_connections
    team_id = resolve_team_id(required=True)
    connections = {str(item["channel_type"]): str(item["connection_id"]) for item in list_connections()
                   if str(item["connection_id"]) == "legacy-" + str(item["channel_type"])}
    changed = 0
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for kind, cid in connections.items():
            kinds = [kind, *({"wework": ["wecom"], "miniprogram": ["miniapp"]}.get(kind, []))]
            for old_kind in kinds:
                for table in ("kellai_messages", "kellai_channel_inbox"):
                    changed += conn.execute(f"UPDATE {table} SET connection_id=?,channel_type=? "
                        "WHERE team_id=? AND connection_id='' AND channel_type=?", (cid, kind, team_id, old_kind)).rowcount
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='kellai_outbound_deliveries'").fetchone():
                    cols = {r[1] for r in conn.execute("PRAGMA table_info(kellai_outbound_deliveries)")}
                    if "connection_id" in cols:
                        conn.execute("UPDATE kellai_outbound_deliveries SET connection_id=? "
                                     "WHERE team_id=? AND connection_id='' AND channel_type=?", (cid, team_id, old_kind))
        rows = conn.execute("SELECT m.* FROM kellai_messages m WHERE m.team_id=? AND m.connection_id<>'' "
            "AND NOT EXISTS(SELECT 1 FROM kellai_transport_contacts c WHERE c.team_id=m.team_id "
            "AND c.connection_id=m.connection_id AND c.channel_type=m.channel_type AND c.contact_id=m.contact_id) "
            "ORDER BY m.created_at", (team_id,)).fetchall()
        for row in rows:
            metadata = _metadata(row["metadata_json"])
            _upsert_contact(conn, team_id=team_id, connection_id=row["connection_id"],
                channel_type=row["channel_type"], contact_id=row["contact_id"], contact_name=row["contact_name"],
                customer_id=row["customer_id"], timestamp=row["created_at"], is_demo=_is_demo(metadata))
    return changed


def _metadata(value: Any) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_demo(metadata: dict) -> bool:
    return bool(metadata.get("simulated") or metadata.get("is_demo") or
                metadata.get("source") in {"closed_loop_audit", "llm_full_flow"})


def _upsert_contact(conn, *, team_id: int, connection_id: str, channel_type: str,
                    contact_id: str, contact_name: str, customer_id: int = 0,
                    timestamp: str = "", is_demo: bool = False) -> int:
    row = conn.execute("SELECT customer_id FROM kellai_transport_contacts WHERE team_id=? AND connection_id=? AND channel_type=? AND contact_id=?",
                       (team_id, connection_id, channel_type, contact_id)).fetchone()
    if row:
        if customer_id > 0 and int(row[0]) != customer_id:
            raise ValueError("联系人地址已关联其他外部客户标识")
        customer_id = int(row[0])
    elif customer_id <= 0:
        customer_id = int(conn.execute("SELECT COALESCE(MAX(customer_id),0)+1 FROM ("
            "SELECT customer_id FROM kellai_transport_contacts WHERE team_id=? UNION ALL "
            "SELECT customer_id FROM kellai_messages WHERE team_id=?)", (team_id, team_id)).fetchone()[0])
    conn.execute("""INSERT INTO kellai_transport_contacts VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(team_id,connection_id,channel_type,contact_id) DO UPDATE SET
        contact_name=CASE WHEN excluded.last_message_at>=last_message_at THEN excluded.contact_name ELSE contact_name END,
        last_message_at=MAX(last_message_at,excluded.last_message_at),is_demo=MAX(is_demo,excluded.is_demo)""",
        (team_id, connection_id, channel_type, contact_id, customer_id, contact_name or contact_id, timestamp, int(is_demo)))
    return customer_id


def register_contact(*, connection_id: str, channel_type: str, contact_id: str,
                     contact_name: str = "", customer_id: int = 0) -> dict:
    team_id = resolve_team_id(required=True)
    cid = _connection_id(connection_id)
    if not contact_id.strip() or len(contact_id) > 256:
        raise ValueError("联系人标识无效")
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        customer_id = _upsert_contact(conn, team_id=team_id, connection_id=cid, channel_type=channel_type,
            contact_id=contact_id, contact_name=contact_name, customer_id=customer_id)
    return get_contact(customer_id, connection_id=cid, channel_type=channel_type, contact_id=contact_id) or {}


def get_contact(customer_id: int, *, connection_id: str, channel_type: str = "", contact_id: str = "") -> dict | None:
    clauses = ["team_id=?", "connection_id=?", "customer_id=?"]
    args: list[Any] = [resolve_team_id(required=True), _connection_id(connection_id), int(customer_id)]
    for name, value in (("channel_type", channel_type), ("contact_id", contact_id)):
        if value:
            clauses.append(name + "=?")
            args.append(value)
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM kellai_transport_contacts WHERE " + " AND ".join(clauses), args).fetchall()
    return dict(rows[0]) if len(rows) == 1 else None


def list_contacts(*, connection_id: str = "", limit: int = 500) -> list[dict]:
    clauses, args = ["team_id=?"], [resolve_team_id(required=True)]
    if connection_id:
        clauses.append("connection_id=?")
        args.append(_connection_id(connection_id))
    args.append(max(1, min(int(limit), 500)))
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM kellai_transport_contacts WHERE " + " AND ".join(clauses) + " ORDER BY last_message_at DESC,customer_id LIMIT ?", args)]


def _message(row) -> UnifiedMessage:
    metadata = {**_metadata(row["metadata_json"]), "team_id": int(row["team_id"]), "connection_id": row["connection_id"]}
    return UnifiedMessage(**{key: row[key] for key in ("id", "connection_id", "customer_id", "channel_type", "contact_id", "contact_name", "direction", "content", "content_type", "created_at")}, metadata=metadata)


def save_message(msg: UnifiedMessage) -> UnifiedMessage:
    metadata = dict(msg.metadata or {})
    team_id = _effective_team_id(metadata=metadata)
    cid = _connection_id(msg.connection_id, metadata=metadata)
    metadata.update(team_id=team_id, connection_id=cid)
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT * FROM kellai_messages WHERE team_id=? AND connection_id=? AND id=?", (team_id, cid, msg.id)).fetchone()
        if previous:
            if any(str(previous[key]) != str(getattr(msg, key)) for key in ("channel_type", "contact_id", "direction", "content", "content_type")):
                raise ValueError("消息编号已绑定其他内容")
            if msg.customer_id > 0 and previous["customer_id"] != msg.customer_id:
                raise ValueError("消息编号已绑定其他联系人")
            return _message(previous)
        customer_id = _upsert_contact(conn, team_id=team_id, connection_id=cid,
            channel_type=msg.channel_type, contact_id=msg.contact_id, contact_name=msg.contact_name,
            customer_id=msg.customer_id, timestamp=msg.created_at, is_demo=_is_demo(metadata))
        conn.execute("INSERT INTO kellai_messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            team_id, cid, msg.id, customer_id, msg.channel_type, msg.contact_id, msg.contact_name,
            msg.direction, msg.content, msg.content_type, json.dumps(metadata, ensure_ascii=False),
            msg.created_at, int(msg.direction != "inbound")))
    return msg.model_copy(update={"customer_id": customer_id, "connection_id": cid, "metadata": metadata})


def get_messages(customer_id: int, channel_type: str = "", limit: int = 50, since: str = "", *,
                 team_id: int | None = None, connection_id: str = "", message_id: str | None = None) -> list[UnifiedMessage]:
    clauses = ["team_id=?", "connection_id=?", "customer_id=?"]
    args: list[Any] = [_effective_team_id(team_id), _connection_id(connection_id), int(customer_id)]
    for column, value, comparator in (("channel_type", channel_type, "="), ("created_at", since, ">"), ("id", message_id, "=")):
        if value:
            clauses.append(column + comparator + "?")
            args.append(value)
    args.append(max(1, min(int(limit), 500)))
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM kellai_messages WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC,id DESC LIMIT ?", args).fetchall()
    return [_message(row) for row in rows]


def get_messages_with_state(customer_id: int, channel_type: str = "", limit: int = 50, since: str = "", **kwargs) -> list[dict]:
    return [message.model_dump() for message in get_messages(customer_id, channel_type, limit, since, **kwargs)]


def push_inbox(channel_type: str, *, contact_id: str, direction: str, content: str,
               contact_name: str = "", content_type: str = "text", metadata: dict | None = None,
               msg_id: str | None = None, team_id: int | None = None, connection_id: str = "") -> str:
    safe = dict(metadata or {})
    tid = _effective_team_id(team_id, metadata=safe)
    cid = _connection_id(connection_id, metadata=safe)
    safe.update(team_id=tid, connection_id=cid)
    mid = msg_id or f"{channel_type}:{secrets.token_hex(16)}"
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT * FROM kellai_channel_inbox WHERE team_id=? AND connection_id=? AND id=?", (tid, cid, mid)).fetchone()
        if previous:
            if (previous["channel_type"], previous["contact_id"], previous["direction"], previous["content"], previous["content_type"]) != (channel_type, contact_id, direction, content, content_type):
                raise ValueError("回调编号已绑定其他消息")
            return mid
        conn.execute("INSERT INTO kellai_channel_inbox VALUES(?,?,?,?,?,?,?,?,?,?,?,0)", (
            tid, cid, mid, channel_type, contact_id, contact_name, direction, content,
            content_type, json.dumps(safe, ensure_ascii=False), _now_iso()))
    return mid


def list_inbox(channel_type: str = "", *, limit: int = 50, include_consumed: bool = False,
               team_id: int | None = None, connection_id: str = "") -> list[dict]:
    clauses = ["team_id=?", "connection_id=?"]
    args: list[Any] = [_effective_team_id(team_id), _connection_id(connection_id)]
    if channel_type:
        clauses.append("channel_type=?")
        args.append(channel_type)
    if not include_consumed:
        clauses.append("consumed=0")
    args.append(max(1, min(int(limit), 500)))
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM kellai_channel_inbox WHERE " + " AND ".join(clauses) + " ORDER BY received_at,id LIMIT ?", args).fetchall()
    return [{**dict(row), "metadata": {**_metadata(row["metadata_json"]), "team_id": row["team_id"], "connection_id": row["connection_id"]}} for row in rows]


def mark_inbox_consumed(message_ids: list[str], *, team_id: int | None = None, connection_id: str = "") -> int:
    if not message_ids:
        return 0
    with _connect() as conn:
        return conn.execute("UPDATE kellai_channel_inbox SET consumed=1 WHERE team_id=? AND connection_id=? AND id IN (" + ",".join("?" for _ in message_ids) + ") AND consumed=0",
                            [_effective_team_id(team_id), _connection_id(connection_id), *message_ids]).rowcount
