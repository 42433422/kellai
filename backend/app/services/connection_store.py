"""Account-scoped connection records; encrypted SQLite is the only credential source."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator

from app.services import credential_vault
from app.services.tenant_context import resolve_team_id, tenant_data_root

REDACTED_VALUE = "********"
_CONNECTION: ContextVar[str] = ContextVar("kellai_connection_id", default="")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_AUTH_TYPES = {"credentials", "oauth2", "browser"}


class ConnectionUnavailable(ValueError):
    pass


class ConnectionConflict(ConnectionUnavailable):
    pass


def current_connection_id(*, required: bool = False) -> str:
    value = _CONNECTION.get()
    if required and not value:
        raise ConnectionUnavailable("必须明确选择 connection_id")
    return value


@contextmanager
def connection_scope(connection_id: str) -> Iterator[None]:
    if not _ID.fullmatch(str(connection_id or "")):
        raise ConnectionUnavailable("connection_id 无效")
    previous = current_connection_id()
    if previous and previous != connection_id:
        raise PermissionError("禁止在账号操作中切换到其他连接")
    # Ownership is checked against the current authenticated workspace.
    get_connection(connection_id)
    token = _CONNECTION.set(connection_id)
    try:
        yield
    finally:
        _CONNECTION.reset(token)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_path():
    root = tenant_data_root(required=True)
    root.mkdir(parents=True, exist_ok=True)
    return root / "connections.sqlite3"


@contextmanager
def database(*, write: bool = False) -> Iterator[sqlite3.Connection]:
    resolve_team_id(required=True)
    connection = sqlite3.connect(str(database_path()), timeout=15.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS connections (
                connection_id TEXT PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                channel_type TEXT NOT NULL,
                name TEXT NOT NULL,
                auth_type TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                connected INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'configured',
                config_enc TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS connection_migrations (
                source TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS connection_oauth_sessions (
                state_hash TEXT PRIMARY KEY, connection_id TEXT NOT NULL,
                owner_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                config_version INTEGER NOT NULL, payload_enc TEXT NOT NULL,
                expires_at INTEGER NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS connection_refresh_leases (
                connection_id TEXT PRIMARY KEY, holder TEXT NOT NULL, expires_at INTEGER NOT NULL
            );
        """)
        if write:
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def is_secret(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in {"headers", "cookies", "storage_state", "credentials", "authorization"} or any(
        word in normalized for word in ("secret", "token", "password", "api_key", "private_key",
                                        "bot_webhook", "encoding_aes_key", "permanent_code"))


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    def redact(key: str, value: Any) -> Any:
        if is_secret(key) and value not in (None, "", {}, []):
            return REDACTED_VALUE
        if isinstance(value, dict):
            return {str(k): redact(str(k), v) for k, v in value.items()}
        if isinstance(value, list):
            return [redact("", item) for item in value]
        return value
    return {str(key): redact(str(key), value) for key, value in config.items()}


def _row(connection: sqlite3.Connection, connection_id: str) -> sqlite3.Row:
    if not _ID.fullmatch(str(connection_id or "")):
        raise ConnectionUnavailable("connection_id 无效")
    row = connection.execute("SELECT * FROM connections WHERE connection_id=? AND owner_id=?",
                             (connection_id, resolve_team_id(required=True))).fetchone()
    if row is None:
        raise KeyError("账号连接不存在")
    return row


def _result(row: sqlite3.Row, *, include_secrets: bool = False) -> dict[str, Any]:
    result = {key: row[key] for key in row.keys() if key not in {"config_enc", "owner_id"}}
    result["enabled"] = bool(result["enabled"])
    result["connected"] = bool(result["connected"])
    if row["status"] == "deleted":
        if include_secrets:
            raise ConnectionUnavailable("账号连接已删除")
        result.update(config={}, credential_state="erased", enabled=False, connected=False)
        return result
    try:
        config = credential_vault.decrypt(row["config_enc"], owner_id=row["owner_id"],
                                          connection_id=row["connection_id"])
    except credential_vault.VaultUnavailable:
        if include_secrets:
            raise
        result.update(config={}, connected=False, status="vault_locked", credential_state="locked")
        return result
    result["config"] = config if include_secrets else redact_config(config)
    result["credential_state"] = "available"
    if not result["enabled"]:
        result["status"] = "disabled"
    if result["auth_type"] == "browser":
        result.update(connected=False, status="executor_required")
    return result


def get_connection(connection_id: str, *, include_secrets: bool = False) -> dict[str, Any]:
    with database() as connection:
        return _result(_row(connection, connection_id), include_secrets=include_secrets)


def list_connections(*, include_deleted: bool = False) -> list[dict[str, Any]]:
    with database() as connection:
        rows = connection.execute("SELECT * FROM connections WHERE owner_id=?" +
                                  ("" if include_deleted else " AND status!='deleted'") +
                                  " ORDER BY created_at, connection_id",
                                  (resolve_team_id(required=True),)).fetchall()
        return [_result(row) for row in rows]


def _insert(connection: sqlite3.Connection, channel_type: str, config: dict[str, Any], *,
            connection_id: str, name: str, auth_type: str, enabled: bool,
            status: str = "configured") -> None:
    owner = resolve_team_id(required=True)
    create_key = connection.execute("SELECT 1 FROM connections WHERE config_enc!='' LIMIT 1").fetchone() is None
    encrypted = credential_vault.encrypt(config, owner_id=owner, connection_id=connection_id,
                                         create_key=create_key)
    now = _now()
    connection.execute("""INSERT INTO connections
        (connection_id,owner_id,channel_type,name,auth_type,enabled,status,config_enc,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (connection_id, owner, channel_type, name or channel_type, auth_type, int(enabled),
         status, encrypted, now, now))


def create_connection(channel_type: str, config: dict[str, Any], *, name: str = "",
                      connection_id: str | None = None, enabled: bool = True,
                      auth_type: str = "credentials") -> dict[str, Any]:
    identifier = connection_id or uuid.uuid4().hex
    if not _ID.fullmatch(identifier) or not _ID.fullmatch(channel_type):
        raise ConnectionUnavailable("账号或渠道标识无效")
    if auth_type not in _AUTH_TYPES:
        raise ConnectionUnavailable("不支持的账号授权方式")
    if not isinstance(config, dict) or len(json.dumps(config, ensure_ascii=False)) > 65536:
        raise ConnectionUnavailable("账号配置无效或过大")
    if any(value == REDACTED_VALUE for value in config.values()):
        raise ConnectionUnavailable("新账号必须提供真实凭据，不能提交脱敏占位值")
    with database(write=True) as connection:
        try:
            _insert(connection, channel_type, config, connection_id=identifier, name=name,
                    auth_type=auth_type, enabled=enabled)
        except sqlite3.IntegrityError as exc:
            raise ConnectionConflict("账号连接已存在") from exc
        return _result(_row(connection, identifier))


def _merge(saved: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    result = dict(saved)
    for key, value in changes.items():
        if is_secret(key) and value == REDACTED_VALUE:
            continue
        if isinstance(value, dict) and value and not is_secret(key) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def update_connection(connection_id: str, config: dict[str, Any] | None = None, *,
                      name: str | None = None, enabled: bool | None = None,
                      connected: bool | None = None, expected_version: int | None = None,
                      status: str | None = None) -> dict[str, Any]:
    with database(write=True) as connection:
        row = _row(connection, connection_id)
        if row["status"] == "deleted":
            raise ConnectionUnavailable("账号连接已删除")
        if expected_version is not None and row["version"] != expected_version:
            raise ConnectionConflict("账号配置已变化，请刷新后重试")
        changed, authorization_changed = False, False
        encrypted = row["config_enc"]
        if config is not None:
            saved = credential_vault.decrypt(row["config_enc"], owner_id=row["owner_id"], connection_id=connection_id)
            merged = _merge(saved, config)
            changed = merged != saved
            authorization_fields = {"provider", "client_id", "client_secret", "client_key", "app_id", "app_secret",
                                    "scope", "redirect_uri"}
            authorization_changed = (row["auth_type"] == "oauth2" or bool(saved.get("oauth_token"))) and any(
                key in config and merged.get(key) != saved.get(key) for key in authorization_fields)
            if authorization_changed:
                merged["oauth_token"] = {}
            if len(json.dumps(merged, ensure_ascii=False)) > 65536:
                raise ConnectionUnavailable("账号配置过大")
            encrypted = credential_vault.encrypt(merged, owner_id=row["owner_id"], connection_id=connection_id)
        state = status or ("configured" if changed else row["status"])
        verified = bool(connected) if connected is not None else (False if changed else bool(row["connected"]))
        if connected is True and status is None:
            state = "authenticated"
        if authorization_changed:
            verified, state = False, "requires_reconnect"
        if row["auth_type"] == "browser":
            verified, state = False, "executor_required"
        connection.execute("""UPDATE connections SET name=?,enabled=?,connected=?,status=?,config_enc=?,
            version=version+1,updated_at=? WHERE connection_id=? AND owner_id=?""",
            (row["name"] if name is None else name,
             row["enabled"] if enabled is None else int(enabled), int(verified), state, encrypted,
             _now(), connection_id, row["owner_id"]))
        return _result(_row(connection, connection_id))


def delete_connection(connection_id: str) -> bool:
    with database(write=True) as connection:
        row = _row(connection, connection_id)
        if row["status"] == "deleted":
            return True
        connection.execute("DELETE FROM connection_oauth_sessions WHERE connection_id=?", (connection_id,))
        connection.execute("DELETE FROM connection_refresh_leases WHERE connection_id=?", (connection_id,))
        # Keep only the identity tombstone referenced by historical messages/receipts.
        connection.execute("""UPDATE connections SET config_enc='',enabled=0,connected=0,status='deleted',
            version=version+1,updated_at=? WHERE connection_id=?""", (_now(), connection_id))
    return True


def require_active(connection_id: str, *, channel_type: str | None = None) -> dict[str, Any]:
    item = get_connection(connection_id, include_secrets=True)
    if not item["enabled"]:
        raise ConnectionUnavailable("账号连接已停用")
    if channel_type is not None and item["channel_type"] != channel_type:
        raise PermissionError("账号连接与渠道不匹配")
    if item["status"] in {"requires_reconnect", "executor_required", "revoked"}:
        raise ConnectionUnavailable("账号需要重新授权或配置执行器")
    return item
