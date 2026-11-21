"""渠道配置持久化层（JSON 文件 · 原子替换）。

跟环境变量双轨：
- 启动时：先读 env，再覆盖为 JSON 中保存的值（用户在前端"保存配置"能即时生效）
- 写入：只写 JSON，不动 env（避免污染运行环境）
- 缺失字段：env 兜底

文件位置：data/tenants/<team>/channel_configs.json。
进程内写入串行化，写入失败会向调用者抛出，不返回虚假的保存成功。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import tempfile
from pathlib import Path
from typing import Any, Optional

from app.services.tenant_context import base_data_root, current_team_id, infer_legacy_owner_team_id, tenant_data_root

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
REDACTED_VALUE = "********"
_CHANNEL_ALIASES = {"wecom": "wework", "miniapp": "miniprogram"}
_FIELD_GROUPS = {
    "wework": [("corp_id", "corpid"), ("secret", "corp_secret", "corpsecret"), ("agent_id", "agentid")],
    "wechat": [("app_id", "appid"), ("app_secret", "appsecret", "secret"),
               ("official_app_id", "mp_app_id"), ("official_app_secret", "mp_app_secret"),
               ("token", "server_token", "webhook_token", "verify_token")],
    "douyin": [("app_id", "client_key"), ("app_secret", "client_secret"),
               ("miniapp_app_id", "miniapp_appid"), ("miniapp_secret", "miniapp_app_secret")],
    "miniprogram": [("app_id", "appid"), ("app_secret", "secret", "appsecret")],
}


def _field_names(channel_type: str, key: str) -> tuple[str, ...]:
    return next((group for group in _FIELD_GROUPS.get(channel_type, []) if key in group), (key,))


def _canonical(channel_type: str) -> str:
    return _CHANNEL_ALIASES.get(channel_type, channel_type)


def _is_secret(key: str) -> bool:
    return any(part in key.lower() for part in (
        "secret", "token", "password", "api_key", "bot_webhook", "encoding_aes_key",
    ))


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a redacted copy. The sentinel is accepted unchanged by save()."""
    return {
        key: redact_config(value) if isinstance(value, dict)
        else REDACTED_VALUE if _is_secret(key) and value not in (None, "") else value
        for key, value in config.items()
    }


def public_config(channel_type: str) -> dict[str, Any]:
    """Effective persisted/environment configuration, with credentials removed."""
    return redact_config(get_all(channel_type))


def environment_config_allowed() -> bool:
    """Server credentials belong to one explicitly bound or legacy sole tenant."""
    team_id = current_team_id()
    if team_id <= 0:
        return True  # Legacy local migration/tests, never an authenticated tenant.
    explicit = os.environ.get("KELLAI_CHANNEL_ENV_TEAM_ID")
    if explicit is not None:
        try:
            return int(explicit) == team_id
        except ValueError:
            return False
    if infer_legacy_owner_team_id() != team_id:
        return False
    path = base_data_root() / "kellai.db"
    if path.exists():
        try:
            with sqlite3.connect(str(path)) as connection:
                if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kellai_teams'").fetchone():
                    teams = connection.execute("SELECT id FROM kellai_teams LIMIT 2").fetchall()
                    return len(teams) == 1 and int(teams[0][0]) == team_id
        except sqlite3.Error:
            return False
    return True

def _config_path() -> Path:
    explicit = (os.environ.get("KELLAI_CHANNEL_CONFIG_PATH") or "").strip()
    team_id = current_team_id()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if team_id > 0:
            return path.parent / "tenants" / str(team_id) / path.name
        return path
    return tenant_data_root(required=False) / "channel_configs.json"


def _ensure_parent() -> None:
    _config_path().parent.mkdir(parents=True, exist_ok=True)


def _read_disk() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("读取渠道配置失败: %s", exc)
        raise


def _write_disk(data: dict[str, Any]) -> None:
    _ensure_parent()
    path = _config_path()
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as stream:
            tmp = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _env_prefixes(channel_type: str) -> list[str]:
    """Return supported KELLAI_* env prefixes for a channel.

    A few public/product names differ from historical env names. Keep both so
    saved configs and deployments upgraded from older builds continue to work.
    """
    primary = channel_type.upper()
    aliases: dict[str, list[str]] = {
        "wework": ["WECOM", "WEWORK"],
        "wecom": ["WECOM", "WEWORK"],
        "miniprogram": ["MINIAPP", "MINIPROGRAM"],
        "miniapp": ["MINIAPP", "MINIPROGRAM"],
        "phone": ["PHONE", "SMS"],
    }
    out = aliases.get(channel_type, [primary])
    if primary not in out:
        out.append(primary)
    return out


def _env_suffixes(channel_type: str, key: str) -> list[str]:
    suffix = key.upper()
    aliases: dict[tuple[str, str], list[str]] = {
        ("wework", "corp_id"): ["CORP_ID", "CORPID"],
        ("wecom", "corp_id"): ["CORP_ID", "CORPID"],
        ("wework", "secret"): ["SECRET", "CORP_SECRET", "CORPSECRET"],
        ("wecom", "secret"): ["SECRET", "CORP_SECRET", "CORPSECRET"],
        ("wework", "corp_secret"): ["CORP_SECRET", "CORPSECRET", "SECRET"],
        ("wecom", "corp_secret"): ["CORP_SECRET", "CORPSECRET", "SECRET"],
        ("douyin", "app_id"): ["APP_ID", "APPID", "CLIENT_KEY"],
        ("douyin", "app_secret"): ["APP_SECRET", "APPSECRET", "CLIENT_SECRET"],
        ("douyin", "client_key"): ["CLIENT_KEY", "APP_ID", "APPID"],
        ("douyin", "client_secret"): ["CLIENT_SECRET", "APP_SECRET", "APPSECRET"],
        ("douyin", "miniapp_app_id"): ["MINIAPP_APP_ID", "MINIAPP_APPID"],
        ("douyin", "miniapp_appid"): ["MINIAPP_APPID", "MINIAPP_APP_ID"],
        ("douyin", "miniapp_secret"): ["MINIAPP_SECRET", "MINIAPP_APP_SECRET"],
        ("douyin", "miniapp_app_secret"): ["MINIAPP_APP_SECRET", "MINIAPP_SECRET"],
        ("wechat", "app_id"): ["APP_ID", "APPID"],
        ("wechat", "appid"): ["APPID", "APP_ID"],
        ("wechat", "app_secret"): ["APP_SECRET", "APPSECRET", "SECRET"],
        ("wechat", "appsecret"): ["APPSECRET", "APP_SECRET", "SECRET"],
        ("wechat", "secret"): ["SECRET", "APP_SECRET", "APPSECRET"],
        ("wechat", "official_app_id"): ["OFFICIAL_APP_ID", "MP_APP_ID"],
        ("wechat", "official_app_secret"): ["OFFICIAL_APP_SECRET", "MP_APP_SECRET"],
        ("wechat", "token"): ["TOKEN", "SERVER_TOKEN", "WEBHOOK_TOKEN", "VERIFY_TOKEN"],
        ("wechat", "server_token"): ["SERVER_TOKEN", "TOKEN", "WEBHOOK_TOKEN", "VERIFY_TOKEN"],
        ("wechat", "webhook_token"): ["WEBHOOK_TOKEN", "TOKEN", "SERVER_TOKEN", "VERIFY_TOKEN"],
        ("miniprogram", "app_id"): ["APP_ID", "APPID"],
        ("miniapp", "app_id"): ["APP_ID", "APPID"],
        ("miniprogram", "app_secret"): ["APP_SECRET", "SECRET", "APPSECRET"],
        ("miniapp", "app_secret"): ["APP_SECRET", "SECRET", "APPSECRET"],
        ("miniprogram", "secret"): ["SECRET", "APP_SECRET", "APPSECRET"],
        ("miniapp", "secret"): ["SECRET", "APP_SECRET", "APPSECRET"],
    }
    out = aliases.get((channel_type, key), [suffix])
    if suffix not in out:
        out.append(suffix)
    return out


def _saved_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Flatten saved channel config while preserving old top-level records."""
    nested = cfg.get("config")
    merged: dict[str, Any] = {}
    if isinstance(nested, dict):
        merged.update(nested)
    for key, value in cfg.items():
        if key in {"config", "name", "enabled", "connected", "createdAt"}:
            continue
        merged.setdefault(key, value)
    return merged


def get(channel_type: str) -> dict[str, Any]:
    """获取某渠道的已保存配置（不含 env 兜底）。"""
    with _LOCK:
        all_cfg = _read_disk()
        canonical = _canonical(channel_type)
        if canonical in all_cfg:
            return dict(all_cfg.get(canonical) or {})
        for alias, target in _CHANNEL_ALIASES.items():
            if target == canonical and alias in all_cfg:
                return dict(all_cfg.get(alias) or {})
        return {}


def get_field(channel_type: str, key: str, default: str = "") -> str:
    """Read JSON > env > default; an explicitly saved empty value revokes it."""
    channel_type = _canonical(channel_type)
    saved = _saved_config(get(channel_type))
    for alias in _field_names(channel_type, key):
        if alias in saved:
            return str(saved[alias]) if saved[alias] is not None else ""
    if not environment_config_allowed():
        return default
    for prefix in _env_prefixes(channel_type):
        for suffix in _env_suffixes(channel_type, key):
            env_val = os.environ.get(f"KELLAI_{prefix}_{suffix}", "").strip()
            if env_val:
                return env_val
    return default


def get_all(channel_type: str) -> dict[str, Any]:
    """获取渠道全量配置（含 env 默认）。"""
    cfg = get(channel_type)
    out = dict(cfg)
    merged_config = _saved_config(cfg)
    allow_environment = environment_config_allowed()
    # env 默认值以"未在前端设置过"为判断标准
    for key in _expected_fields(channel_type):
        saved_alias = next((alias for alias in _field_names(_canonical(channel_type), key)
                            if alias in merged_config), None)
        if saved_alias is not None:
            merged_config[key] = merged_config[saved_alias]
            continue
        if not allow_environment:
            continue
        for prefix in _env_prefixes(channel_type):
            for suffix in _env_suffixes(channel_type, key):
                env_val = os.environ.get(f"KELLAI_{prefix}_{suffix}", "").strip()
                if env_val:
                    merged_config.setdefault(key, env_val)
                    break
            if key in merged_config and merged_config[key]:
                break
    out["config"] = merged_config
    return out


def _expected_fields(channel_type: str) -> list[str]:
    """前端可能配置的所有字段名（key 集合）。"""
    map_: dict[str, list[str]] = {
        "wework": ["corp_id", "secret", "agent_id", "bot_webhook", "kf_url", "open_kfid"],
        "wecom": ["corp_id", "secret", "agent_id", "bot_webhook", "kf_url", "open_kfid"],
        "wechat": [
            "app_id",
            "app_secret",
            "official_app_id",
            "official_app_secret",
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


def save(channel_type: str, config: dict[str, Any], *, name: Optional[str] = None,
         enabled: Optional[bool] = None, connected: Optional[bool] = None) -> dict[str, Any]:
    """保存渠道配置。

    写回磁盘并返回该渠道的最终状态 dict（含 name/enabled/connected）。
    """
    with _LOCK:
        channel_type = _canonical(channel_type)
        all_cfg = _read_disk()
        cur = get(channel_type)
        # 合并：保留原 name/enabled，只覆盖 config
        new_cfg = dict(cur)
        incoming_config = {key: value for key, value in (config or {}).items()
                           if not (_is_secret(key) and value == REDACTED_VALUE)}
        for group in _FIELD_GROUPS.get(channel_type, []):
            supplied = [incoming_config[key] for key in group if key in incoming_config]
            if supplied:
                if any(value != supplied[0] for value in supplied):
                    raise ValueError("渠道配置的同义字段值不一致: " + ", ".join(group))
                incoming_config.update({key: supplied[0] for key in group})
        merged_config = _saved_config(cur)
        changed = any(key not in merged_config or merged_config[key] != value
                      for key, value in incoming_config.items())
        merged_config.update(incoming_config)
        new_cfg["config"] = merged_config
        if name is not None:
            new_cfg["name"] = str(name)
        if enabled is not None:
            new_cfg["enabled"] = bool(enabled)
        if connected is not None:
            new_cfg["connected"] = bool(connected)
        elif changed:
            # 凭据变更后必须重新测试，避免“已保存”误显示为“已接入”。
            new_cfg["connected"] = False
        new_cfg.setdefault("name", channel_type)
        new_cfg.setdefault("enabled", False)
        new_cfg.setdefault("connected", False)
        all_cfg[channel_type] = new_cfg
        _write_disk(all_cfg)
        return new_cfg


def delete(channel_type: str) -> bool:
    """删除渠道配置（断开/取消配置）。"""
    with _LOCK:
        channel_type = _canonical(channel_type)
        all_cfg = _read_disk()
        keys = {channel_type, *[key for key, value in _CHANNEL_ALIASES.items() if value == channel_type]}
        if not keys.intersection(all_cfg):
            return False
        for key in keys:
            all_cfg.pop(key, None)
        _write_disk(all_cfg)
        return True


def list_all() -> dict[str, dict[str, Any]]:
    """列出所有已保存的渠道配置。"""
    with _LOCK:
        return dict(_read_disk())
