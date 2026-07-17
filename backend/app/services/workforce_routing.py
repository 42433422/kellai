"""统一工作台员工在线状态、客户归属与负载均衡路由。"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.services.crm_store import _crm_db_path


PRESENCE_TTL_SECONDS = 45
ACTIVE_LOAD_WINDOW_SECONDS = 7 * 24 * 60 * 60


class AssignmentConflict(RuntimeError):
    """客户已被其他成员领取。"""

    def __init__(self, message: str, assignment: dict[str, Any] | None = None):
        super().__init__(message)
        self.assignment = assignment


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> int:
    return int(time.time())


def ensure_schema() -> None:
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kellai_employee_presence (
                team_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reported_state TEXT NOT NULL DEFAULT 'online',
                last_heartbeat_ts INTEGER NOT NULL DEFAULT 0,
                last_heartbeat_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (team_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_presence_team_heartbeat
                ON kellai_employee_presence(team_id, last_heartbeat_ts);

            CREATE TABLE IF NOT EXISTS kellai_customer_assignments (
                customer_id INTEGER PRIMARY KEY,
                team_id INTEGER NOT NULL,
                assignee_user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'assigned',
                source TEXT NOT NULL DEFAULT 'auto',
                assigned_by_user_id INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 1,
                assigned_at TEXT NOT NULL,
                last_activity_ts INTEGER NOT NULL DEFAULT 0,
                last_activity_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_assignments_team_assignee
                ON kellai_customer_assignments(team_id, assignee_user_id, status);
            CREATE INDEX IF NOT EXISTS idx_assignments_activity
                ON kellai_customer_assignments(team_id, last_activity_ts);

            CREATE TABLE IF NOT EXISTS kellai_assignment_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                assignee_user_id INTEGER NOT NULL DEFAULT 0,
                actor_user_id INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT '',
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_assignment_events_customer
                ON kellai_assignment_events(customer_id, id);
            """
        )
        conn.commit()


@contextmanager
def _conn(*, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    ensure_schema()
    conn = sqlite3.connect(str(_crm_db_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def heartbeat(*, team_id: int, user_id: int, state: str = "online") -> dict[str, Any]:
    if int(team_id) <= 0 or int(user_id) <= 0:
        raise ValueError("缺少有效团队或用户")
    reported_state = str(state or "online").strip().lower()
    if reported_state not in {"online", "busy", "away"}:
        reported_state = "online"
    now_ts = _now_ts()
    now = _now_iso()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO kellai_employee_presence
                (team_id, user_id, reported_state, last_heartbeat_ts,
                 last_heartbeat_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(team_id, user_id) DO UPDATE SET
                reported_state = excluded.reported_state,
                last_heartbeat_ts = excluded.last_heartbeat_ts,
                last_heartbeat_at = excluded.last_heartbeat_at,
                updated_at = excluded.updated_at
            """,
            (int(team_id), int(user_id), reported_state, now_ts, now, now),
        )
    return {
        "team_id": int(team_id),
        "user_id": int(user_id),
        "reported_state": reported_state,
        "online": True,
        "last_heartbeat_at": now,
    }


def _team_members(team_id: int) -> list[dict[str, Any]]:
    from app.services.auth import list_team_members

    return [
        member
        for member in list_team_members(int(team_id))
        if bool(member.get("is_active", True))
        and str(member.get("role") or "") in {"owner", "admin", "sales"}
    ]


def presence_snapshot(team_id: int) -> list[dict[str, Any]]:
    now_ts = _now_ts()
    active_since = now_ts - ACTIVE_LOAD_WINDOW_SECONDS
    members = _team_members(team_id)
    with _conn() as conn:
        presence_rows = conn.execute(
            """
            SELECT *
            FROM kellai_employee_presence
            WHERE team_id = ?
            """,
            (int(team_id),),
        ).fetchall()
        load_rows = conn.execute(
            """
            SELECT assignee_user_id, COUNT(*) AS active_count,
                   MAX(assigned_at) AS last_assigned_at
            FROM kellai_customer_assignments
            WHERE team_id = ? AND status = 'assigned' AND last_activity_ts >= ?
            GROUP BY assignee_user_id
            """,
            (int(team_id), active_since),
        ).fetchall()
    presence_by_user = {int(row["user_id"]): row for row in presence_rows}
    load_by_user = {
        int(row["assignee_user_id"]): {
            "active_count": int(row["active_count"] or 0),
            "last_assigned_at": str(row["last_assigned_at"] or ""),
        }
        for row in load_rows
    }
    result: list[dict[str, Any]] = []
    for member in members:
        user_id = int(member["id"])
        presence = presence_by_user.get(user_id)
        last_seen_ts = int(presence["last_heartbeat_ts"] or 0) if presence else 0
        online = bool(last_seen_ts and now_ts - last_seen_ts <= PRESENCE_TTL_SECONDS)
        reported_state = str(presence["reported_state"] or "online") if presence else "offline"
        active_count = int(load_by_user.get(user_id, {}).get("active_count") or 0)
        if not online:
            availability = "offline"
        elif reported_state == "away":
            availability = "away"
        elif reported_state == "busy" or active_count > 0:
            availability = "busy"
        else:
            availability = "idle"
        result.append(
            {
                "user_id": user_id,
                "team_id": int(team_id),
                "display_name": str(
                    member.get("display_name")
                    or member.get("email")
                    or member.get("phone")
                    or f"成员{user_id}"
                ),
                "avatar_url": str(member.get("avatar_url") or ""),
                "role": str(member.get("role") or "sales"),
                "online": online,
                "reported_state": reported_state,
                "availability": availability,
                "active_count": active_count,
                "last_heartbeat_at": (
                    str(presence["last_heartbeat_at"] or "") if presence else ""
                ),
                "last_assigned_at": str(
                    load_by_user.get(user_id, {}).get("last_assigned_at") or ""
                ),
            }
        )
    result.sort(
        key=lambda row: (
            not bool(row["online"]),
            row["availability"] != "idle",
            int(row["active_count"]),
            str(row["last_assigned_at"]),
            int(row["user_id"]),
        )
    )
    return result


def _assignment_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = set(row.keys())
    return {
        "customer_id": int(row["customer_id"]),
        "team_id": int(row["team_id"]),
        "assignee_user_id": int(row["assignee_user_id"]),
        "assignee_name": (
            str(row["assignee_name"] or "")
            if "assignee_name" in keys
            else ""
        ),
        "assignee_role": (
            str(row["assignee_role"] or "")
            if "assignee_role" in keys
            else ""
        ),
        "status": str(row["status"]),
        "source": str(row["source"]),
        "assigned_by_user_id": int(row["assigned_by_user_id"] or 0),
        "version": int(row["version"] or 1),
        "assigned_at": str(row["assigned_at"]),
        "last_activity_at": str(row["last_activity_at"] or ""),
        "updated_at": str(row["updated_at"]),
    }


def _select_assignment(conn: sqlite3.Connection, customer_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT a.*, u.display_name AS assignee_name, u.role AS assignee_role
        FROM kellai_customer_assignments a
        LEFT JOIN kellai_users u ON u.id = a.assignee_user_id
        WHERE a.customer_id = ?
        """,
        (int(customer_id),),
    ).fetchone()


def assignment_for_customer(customer_id: int) -> dict[str, Any] | None:
    with _conn() as conn:
        return _assignment_dict(_select_assignment(conn, int(customer_id)))


def _record_event(
    conn: sqlite3.Connection,
    *,
    customer_id: int,
    team_id: int,
    action: str,
    assignee_user_id: int = 0,
    actor_user_id: int = 0,
    source: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO kellai_assignment_events
            (customer_id, team_id, action, assignee_user_id, actor_user_id,
             source, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(customer_id),
            int(team_id),
            str(action),
            int(assignee_user_id),
            int(actor_user_id),
            str(source),
            json.dumps(detail or {}, ensure_ascii=False),
            _now_iso(),
        ),
    )


def _sync_pipeline_owner(customer_id: int, assignment: dict[str, Any] | None) -> None:
    try:
        from app.services.pipeline import load_pipeline, save_pipeline

        doc = load_pipeline(int(customer_id))
        if assignment and assignment.get("status") == "assigned":
            doc["team_id"] = int(assignment.get("team_id") or doc.get("team_id") or 0)
            doc["owner"] = str(
                assignment.get("assignee_name")
                or f"成员{assignment.get('assignee_user_id')}"
            )
            doc["owner_user_id"] = int(assignment.get("assignee_user_id") or 0)
            doc["assignment_source"] = str(assignment.get("source") or "")
            doc["assignment_status"] = "assigned"
        else:
            doc["owner"] = ""
            doc["owner_user_id"] = 0
            doc["assignment_source"] = ""
            doc["assignment_status"] = "unassigned"
        save_pipeline(doc)
    except Exception:
        # 分配表是 SSOT；客户档案同步失败不应破坏原子分配。
        return


def assign_customer(
    *,
    customer_id: int,
    team_id: int,
    assignee_user_id: int,
    actor_user_id: int,
    source: str = "manual",
    allow_override: bool = True,
) -> dict[str, Any]:
    now = _now_iso()
    now_ts = _now_ts()
    with _conn(immediate=True) as conn:
        member = conn.execute(
            """
            SELECT id, display_name, role, is_active
            FROM kellai_users
            WHERE id = ? AND team_id = ?
            """,
            (int(assignee_user_id), int(team_id)),
        ).fetchone()
        if (
            member is None
            or not bool(member["is_active"])
            or str(member["role"]) not in {"owner", "admin", "sales"}
        ):
            raise ValueError("指定成员不在当前团队或没有接待权限")
        existing = _select_assignment(conn, int(customer_id))
        existing_data = _assignment_dict(existing)
        if (
            existing_data
            and existing_data["status"] == "assigned"
            and int(existing_data["assignee_user_id"]) != int(assignee_user_id)
            and not allow_override
        ):
            raise AssignmentConflict(
                f"该客户已由 {existing_data.get('assignee_name') or '其他成员'} 承接",
                existing_data,
            )
        next_version = int(existing_data.get("version") or 0) + 1 if existing_data else 1
        assigned_at = (
            str(existing_data.get("assigned_at") or now)
            if existing_data
            and int(existing_data.get("assignee_user_id") or 0) == int(assignee_user_id)
            else now
        )
        conn.execute(
            """
            INSERT INTO kellai_customer_assignments
                (customer_id, team_id, assignee_user_id, status, source,
                 assigned_by_user_id, version, assigned_at, last_activity_ts,
                 last_activity_at, updated_at)
            VALUES (?, ?, ?, 'assigned', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(customer_id) DO UPDATE SET
                team_id = excluded.team_id,
                assignee_user_id = excluded.assignee_user_id,
                status = 'assigned',
                source = excluded.source,
                assigned_by_user_id = excluded.assigned_by_user_id,
                version = excluded.version,
                assigned_at = excluded.assigned_at,
                last_activity_ts = excluded.last_activity_ts,
                last_activity_at = excluded.last_activity_at,
                updated_at = excluded.updated_at
            """,
            (
                int(customer_id),
                int(team_id),
                int(assignee_user_id),
                str(source),
                int(actor_user_id),
                next_version,
                assigned_at,
                now_ts,
                now,
                now,
            ),
        )
        _record_event(
            conn,
            customer_id=customer_id,
            team_id=team_id,
            action="assigned",
            assignee_user_id=assignee_user_id,
            actor_user_id=actor_user_id,
            source=source,
            detail={
                "previous_assignee_user_id": (
                    int(existing_data.get("assignee_user_id") or 0)
                    if existing_data
                    else 0
                )
            },
        )
        assignment = _assignment_dict(_select_assignment(conn, int(customer_id))) or {}
    _sync_pipeline_owner(customer_id, assignment)
    return assignment


def claim_customer(*, customer_id: int, team_id: int, user_id: int) -> dict[str, Any]:
    return assign_customer(
        customer_id=customer_id,
        team_id=team_id,
        assignee_user_id=user_id,
        actor_user_id=user_id,
        source="claim",
        allow_override=False,
    )


def auto_assign_customer(
    *,
    customer_id: int,
    team_id: int,
    source: str = "auto_route",
) -> dict[str, Any] | None:
    existing = assignment_for_customer(customer_id)
    if (
        existing
        and existing.get("status") == "assigned"
        and int(existing.get("team_id") or 0) == int(team_id)
    ):
        touch_assignment(customer_id)
        return assignment_for_customer(customer_id)
    candidates = presence_snapshot(team_id)
    if not candidates:
        return None
    online = [
        row
        for row in candidates
        if row["online"] and row["availability"] not in {"away", "offline"}
    ]
    pool = online or candidates
    selected = min(
        pool,
        key=lambda row: (
            row["availability"] != "idle",
            int(row["active_count"]),
            str(row["last_assigned_at"]),
            int(row["user_id"]),
        ),
    )
    return assign_customer(
        customer_id=customer_id,
        team_id=team_id,
        assignee_user_id=int(selected["user_id"]),
        actor_user_id=0,
        source=source if online else f"{source}_offline_fallback",
        allow_override=False,
    )


def touch_assignment(customer_id: int) -> bool:
    now = _now_iso()
    with _conn() as conn:
        cur = conn.execute(
            """
            UPDATE kellai_customer_assignments
            SET last_activity_ts = ?, last_activity_at = ?, updated_at = ?
            WHERE customer_id = ? AND status = 'assigned'
            """,
            (_now_ts(), now, now, int(customer_id)),
        )
        return bool(cur.rowcount)


def release_customer(
    *,
    customer_id: int,
    team_id: int,
    actor_user_id: int,
) -> dict[str, Any] | None:
    now = _now_iso()
    with _conn(immediate=True) as conn:
        existing = _select_assignment(conn, int(customer_id))
        data = _assignment_dict(existing)
        if data is None or int(data["team_id"]) != int(team_id):
            return None
        conn.execute(
            """
            UPDATE kellai_customer_assignments
            SET status = 'released', version = version + 1, updated_at = ?
            WHERE customer_id = ?
            """,
            (now, int(customer_id)),
        )
        _record_event(
            conn,
            customer_id=customer_id,
            team_id=team_id,
            action="released",
            assignee_user_id=int(data["assignee_user_id"]),
            actor_user_id=actor_user_id,
            source="manual",
        )
        released = _assignment_dict(_select_assignment(conn, int(customer_id)))
    _sync_pipeline_owner(customer_id, None)
    return released


def list_assignments(team_id: int, *, limit: int = 500) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT a.*, u.display_name AS assignee_name, u.role AS assignee_role
            FROM kellai_customer_assignments a
            LEFT JOIN kellai_users u ON u.id = a.assignee_user_id
            WHERE a.team_id = ?
            ORDER BY a.last_activity_ts DESC, a.customer_id DESC
            LIMIT ?
            """,
            (int(team_id), max(1, min(int(limit), 1000))),
        ).fetchall()
    return [
        assignment
        for row in rows
        if (assignment := _assignment_dict(row)) is not None
    ]


def routing_overview(team_id: int) -> dict[str, Any]:
    presence = presence_snapshot(team_id)
    assignments = list_assignments(team_id)
    return {
        "presence": presence,
        "assignments": assignments,
        "online_count": sum(1 for row in presence if row["online"]),
        "idle_count": sum(1 for row in presence if row["availability"] == "idle"),
        "assigned_count": sum(1 for row in assignments if row["status"] == "assigned"),
    }
