"""Connection-scoped adapter configuration backed solely by the encrypted vault."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.services import connection_store as store
from app.services.connection_store import (
    ConnectionUnavailable, ConnectionConflict, REDACTED_VALUE,
    current_connection_id, redact_config, is_secret as _is_secret,
)
from app.services.tenant_context import (
    base_data_root, current_team_id, infer_legacy_owner_team_id, tenant_data_root,
)

_CHANNEL_ALIASES = {"wecom": "wework", "miniapp": "miniprogram"}
_FIELD_GROUPS = {
    "wework": [("corp_id", "corpid"), ("secret", "corp_secret", "corpsecret"), ("agent_id", "agentid")],
    "wechat": [("app_id", "appid"), ("app_secret", "appsecret", "secret"),
               ("official_app_id", "mp_app_id"), ("official_app_secret", "mp_app_secret"),
               ("official_original_id", "original_id"),
               ("token", "server_token", "webhook_token", "verify_token")],
    "douyin": [("app_id", "client_key"), ("app_secret", "client_secret"),
               ("miniapp_app_id", "miniapp_appid"), ("miniapp_secret", "miniapp_app_secret")],
    "miniprogram": [("app_id", "appid"), ("app_secret", "secret", "appsecret")],
}



def _canonical(channel_type: str) -> str:
    return _CHANNEL_ALIASES.get(channel_type, channel_type)


def _field_names(channel_type: str, key: str) -> tuple[str, ...]:
    return next((group for group in _FIELD_GROUPS.get(channel_type, []) if key in group), (key,))


def _normalize(channel_type: str, config: dict[str, Any]) -> dict[str, Any]:
    output = dict(config)
    for group in _FIELD_GROUPS.get(_canonical(channel_type), []):
        supplied = [output[key] for key in group if key in output and output[key] != REDACTED_VALUE]
        if supplied:
            if any(value != supplied[0] for value in supplied):
                raise ValueError("渠道配置的同义字段值不一致")
            output.update({key: supplied[0] for key in group})
    return output


def environment_config_allowed() -> bool:
    # Credentials have one source; importing legacy files never re-enables env fallback.
    return False


def _config_path() -> Path:
    explicit = (os.environ.get("KELLAI_CHANNEL_CONFIG_PATH") or "").strip()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path.parent / "tenants" / str(current_team_id()) / path.name
    return tenant_data_root() / "channel_configs.json"


def _migrate_file(path: Path) -> int:
    """Encrypt a legacy channel file transactionally, then remove its old credential source.

    A committed marker permits cleanup after a crash. If the file changed after
    migration, fail rather than deleting new user data or restoring an old account.
    """
    if not path.is_file():
        return 0
    raw = path.read_bytes()
    fingerprint = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ConnectionUnavailable("旧账号配置格式无效，迁移已停止")
    migrated = 0
    with store.database(write=True) as database:
        marker = database.execute("SELECT fingerprint FROM connection_migrations WHERE source=?",
                                  (str(path),)).fetchone()
        if marker:
            if marker["fingerprint"] != fingerprint:
                raise ConnectionConflict("旧配置在迁移后发生变化，请先处理冲突")
        else:
            canonical: dict[str, dict] = {}
            for kind, record in data.items():
                if not isinstance(record, dict):
                    raise ConnectionUnavailable("旧账号配置格式无效，迁移已停止")
                channel = _canonical(str(kind))
                if channel in canonical and canonical[channel] != record:
                    raise ConnectionConflict("旧渠道别名存在不同账号配置，必须先明确归属")
                canonical[channel] = record
            for channel, record in canonical.items():
                if not store._ID.fullmatch(channel):
                    raise ConnectionUnavailable("旧渠道标识无效，迁移已停止")
                config = dict(record.get("config") or {})
                for key, value in record.items():
                    if key not in {"config", "name", "enabled", "connected", "createdAt"}:
                        config.setdefault(key, value)
                identifier = "legacy-" + channel
                existing = database.execute("SELECT * FROM connections WHERE connection_id=?",
                                            (identifier,)).fetchone()
                if existing is not None:
                    saved = store._result(existing, include_secrets=True)
                    if saved["config"] != _normalize(channel, config):
                        raise ConnectionConflict("旧根目录配置与账号配置不同，请先处理迁移冲突")
                    continue
                # Third-party authorization/desktop bridges require a new explicit
                # account authorization. Their old service tables are never read.
                reconnect = channel in {"douyin", "wework"} and bool(
                    config.get("oauth_authorized") or config.get("remote_credentials_configured")
                    or config.get("suite_id") or config.get("remote_miniapp_configured"))
                store._insert(database, channel, _normalize(channel, config), connection_id=identifier,
                              name=str(record.get("name") or channel), auth_type="credentials",
                              enabled=bool(record.get("enabled", False)),
                              status="requires_reconnect" if reconnect else "configured")
                migrated += 1
            database.execute("INSERT INTO connection_migrations VALUES (?,?,?)",
                             (str(path), fingerprint, store._now()))
    # Only remove the exact bytes we committed. No fallback ever reads this file.
    if hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint:
        raise ConnectionConflict("旧配置在迁移时被修改，未删除该文件")
    path.unlink()
    return migrated


def _root_owner_is_proven() -> bool:
    owner = current_team_id()
    if owner <= 0 or infer_legacy_owner_team_id() != owner:
        return False
    root = base_data_root()
    candidates = {int(path.name) for path in (root / "tenants").glob("*")
                  if path.is_dir() and path.name.isdigit() and int(path.name) > 0}
    db_path = root / "kellai.db"
    if db_path.exists():
        with sqlite3.connect(str(db_path)) as database:
            tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, column in (("kellai_teams", "id"), ("kellai_messages", "team_id"),
                                  ("kellai_outbound_deliveries", "team_id")):
                if table in tables and column in {row[1] for row in database.execute(f"PRAGMA table_info({table})")}:
                    candidates.update(int(row[0]) for row in database.execute(
                        f"SELECT DISTINCT {column} FROM {table} WHERE {column}>0"))
    return candidates <= {owner}


def migrate_legacy() -> dict[str, Any]:
    namespaced = _config_path()
    explicit = (os.environ.get("KELLAI_CHANNEL_CONFIG_PATH") or "").strip()
    root = Path(explicit).expanduser().resolve() if explicit else base_data_root() / "channel_configs.json"
    if root.is_file() and root != namespaced and not _root_owner_is_proven():
        raise ConnectionUnavailable("旧根目录账号配置归属不明，迁移已阻止；请先核对历史工作区归属")
    migrated = _migrate_file(namespaced)
    if root != namespaced:
        migrated += _migrate_file(root)
    return {"migrated": migrated}


@contextmanager
def connection_scope(connection_id: str):
    migrate_legacy()
    with store.connection_scope(connection_id):
        yield


def list_connections(*, include_deleted: bool = False) -> list[dict[str, Any]]:
    migrate_legacy()
    return store.list_connections(include_deleted=include_deleted)


def get_connection(connection_id: str, *, include_secrets: bool = False) -> dict[str, Any]:
    migrate_legacy()
    return store.get_connection(connection_id, include_secrets=include_secrets)


def create_connection(channel_type: str, config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    migrate_legacy()
    channel = _canonical(channel_type)
    return store.create_connection(channel, _normalize(channel, config), **kwargs)


def update_connection(connection_id: str, config: dict[str, Any] | None = None,
                      **kwargs: Any) -> dict[str, Any]:
    item = get_connection(connection_id)
    normalized = _normalize(item["channel_type"], config) if config is not None else None
    return store.update_connection(connection_id, normalized, **kwargs)


def delete_connection(connection_id: str) -> bool:
    migrate_legacy()
    return store.delete_connection(connection_id)


def get(channel_type: str) -> dict[str, Any]:
    item = get_connection(current_connection_id(required=True), include_secrets=True)
    if item["channel_type"] != _canonical(channel_type):
        raise PermissionError("账号连接与渠道不匹配")
    return item


def get_all(channel_type: str) -> dict[str, Any]:
    return get(channel_type)


def get_field(channel_type: str, key: str, default: str = "") -> str:
    config = get(channel_type)["config"]
    for alias in _field_names(_canonical(channel_type), key):
        if alias in config:
            return str(config[alias]) if config[alias] is not None else ""
    return default


def public_config(channel_type: str) -> dict[str, Any]:
    return redact_config(get(channel_type))


def save(channel_type: str, config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    # Retained only as the adapter's scoped write helper, never a channel-wide store.
    item = get(channel_type)
    return update_connection(item["connection_id"], config, **kwargs)


def config_schema(channel_type: str) -> dict[str, Any]:
    fields = _expected_fields(channel_type)
    return {"type": "object", "properties": {
        key: {"type": "string", "title": key.replace("_", " "),
              **({"writeOnly": True} if _is_secret(key) else {})}
        for key in fields if not key.startswith(("oauth_", "remote_"))
    }}

def _expected_fields(channel_type: str) -> list[str]:
    """前端可能配置的所有字段名（key 集合）。"""
    map_: dict[str, list[str]] = {
        "wework": ["corp_id", "secret", "agent_id", "bot_webhook", "kf_url", "open_kfid",
                   "webhook_token", "encoding_aes_key"],
        "wecom": ["corp_id", "secret", "agent_id", "bot_webhook", "kf_url", "open_kfid"],
        "wechat": [
            "app_id",
            "app_secret",
            "official_app_id",
            "official_app_secret",
            "official_original_id",
            "token",
            "server_token",
            "webhook_token",
            "encoding_aes_key",
            "bot_webhook",
            "oauth_authorized",
            "oauth_openid",
            "oauth_unionid",
            "oauth_scope",
            "oauth_refresh_token",
        ],
        "douyin": [
            "app_id",
            "app_secret",
            "client_key",
            "client_secret",
            "scope",
            "miniapp_app_id",
            "miniapp_secret",
            "oauth_authorized",
            "oauth_open_id",
            "oauth_scope",
            "oauth_account_name",
            "remote_credentials_configured",
            "remote_miniapp_configured",
        ],
        "miniprogram": ["app_id", "app_secret", "template_id"],
        "miniapp": ["app_id", "app_secret", "template_id"],
        "pdd": ["client_id", "client_secret"],
        "taobao": ["app_key", "app_secret"],
        "jd": ["app_key", "app_secret"],
        "alibaba": ["app_key", "app_secret"],
        "whatsapp": ["phone_number_id", "access_token", "business_id"],
        "telegram": ["bot_token"],
        "line": ["channel_access_token", "channel_secret"],
        "phone": ["provider", "account_sid", "auth_token", "from_number", "access_key_id",
                  "access_key_secret", "sign_name", "template_code"],
        "chatwoot": ["base_url", "account_id", "inbox_id", "api_access_token", "webhook_secret"],
        "email": ["smtp_host", "smtp_port", "smtp_user", "smtp_password"],
        "sms": ["provider", "api_key", "api_secret"],
    }
    return map_.get(channel_type, [])
