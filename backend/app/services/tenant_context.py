"""Request-scoped tenant identity and tenant filesystem namespaces.

The authenticated user is the only authority for normal product requests.
Callers may pass an explicit team only from already-authenticated internal
channel flows; an explicit team that conflicts with the request context is
rejected instead of silently switching tenants.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Iterator


class TenantIsolationError(PermissionError):
    """Raised when data access has no tenant or crosses a tenant boundary."""


_TEAM_ID: ContextVar[int] = ContextVar("kellai_team_id", default=0)
_USER_ID: ContextVar[int] = ContextVar("kellai_user_id", default=0)


def current_team_id() -> int:
    return int(_TEAM_ID.get() or 0)


def current_user_id() -> int:
    return int(_USER_ID.get() or 0)


def resolve_team_id(explicit_team_id: int | None = None, *, required: bool = False) -> int:
    context_team = current_team_id()
    explicit = int(explicit_team_id or 0)
    if context_team > 0 and explicit > 0 and context_team != explicit:
        raise TenantIsolationError("请求租户与数据租户不一致")
    resolved = context_team or explicit
    if required and resolved <= 0:
        raise TenantIsolationError("缺少有效租户上下文")
    return resolved


def bind_request_tenant(user: dict | None) -> tuple[Token[int], Token[int]]:
    payload = user if isinstance(user, dict) else {}
    team_token = _TEAM_ID.set(int(payload.get("team_id") or 0))
    user_token = _USER_ID.set(int(payload.get("id") or 0))
    return team_token, user_token


def reset_request_tenant(tokens: tuple[Token[int], Token[int]]) -> None:
    team_token, user_token = tokens
    _USER_ID.reset(user_token)
    _TEAM_ID.reset(team_token)


@contextmanager
def tenant_scope(team_id: int, *, user_id: int = 0) -> Iterator[None]:
    resolved = int(team_id or 0)
    if resolved <= 0:
        raise TenantIsolationError("缺少有效租户上下文")
    existing = current_team_id()
    if existing > 0 and existing != resolved:
        raise TenantIsolationError("禁止切换到其他租户")
    tokens = (_TEAM_ID.set(resolved), _USER_ID.set(int(user_id or current_user_id())))
    try:
        yield
    finally:
        reset_request_tenant(tokens)


def base_data_root() -> Path:
    configured = (os.environ.get("KELLAI_DATA_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "data"


def tenant_data_root(team_id: int | None = None, *, required: bool = True) -> Path:
    resolved = resolve_team_id(team_id, required=required)
    root = base_data_root()
    if resolved <= 0:
        return root
    return root / "tenants" / str(resolved)


def legacy_owner_candidates(root: Path | None = None) -> set[int]:
    root = root or base_data_root()
    teams = {int(path.name) for path in (root / "tenants").glob("*")
             if path.is_dir() and path.name.isdigit() and int(path.name) > 0}
    pipeline_dir = root / "pipelines"
    if pipeline_dir.is_dir():
        for path in pipeline_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                team_id = int((payload or {}).get("team_id") or 0)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if team_id > 0:
                teams.add(team_id)
    db_path = root / "kellai.db"
    if db_path.is_file():
        try:
            with sqlite3.connect(str(db_path)) as conn:
                for table in ("kellai_teams", "kellai_messages", "kellai_channel_inbox", "kellai_outbound_deliveries"):
                    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        continue
                    columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
                    column = "id" if table == "kellai_teams" else "team_id"
                    if column in columns:
                        rows = conn.execute(f"SELECT DISTINCT {column} FROM {table} WHERE {column}>0").fetchall()
                        teams.update(int(row[0]) for row in rows)
                    if "metadata_json" in columns:
                        rows = conn.execute(f"SELECT DISTINCT CAST(json_extract(metadata_json,'$.team_id') AS INTEGER) "
                                            f"FROM {table} WHERE json_valid(metadata_json)" +
                                            (" AND team_id<=0" if "team_id" in columns else "")).fetchall()
                        teams.update(int(row[0]) for row in rows if int(row[0] or 0) > 0)
        except sqlite3.Error:
            pass
    return teams


def infer_legacy_owner_team_id() -> int:
    teams = legacy_owner_candidates()
    return next(iter(teams)) if len(teams) == 1 else 0


__all__ = [
    "TenantIsolationError",
    "base_data_root",
    "bind_request_tenant",
    "current_team_id",
    "current_user_id",
    "infer_legacy_owner_team_id",
    "legacy_owner_candidates",
    "reset_request_tenant",
    "resolve_team_id",
    "tenant_data_root",
    "tenant_scope",
]
