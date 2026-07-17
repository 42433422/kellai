"""渠道配置持久化层（JSON 文件 · 跨进程共享）。

跟环境变量双轨：
- 启动时：先读 env，再覆盖为 JSON 中保存的值（用户在前端"保存配置"能即时生效）
- 写入：只写 JSON，不动 env（避免污染运行环境）
- 缺失字段：env 兜底

文件位置：data/channel_configs.json
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

_CONFIG_PATH = Path(
    os.environ.get("KELLAI_CHANNEL_CONFIG_PATH")
    or str(Path(__file__).resolve().parents[3] / "data" / "channel_configs.json")
)


def _ensure_parent() -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _read_disk() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        raw = _CONFIG_PATH.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("读取渠道配置失败: %s", exc)
        return {}


def _write_disk(data: dict[str, Any]) -> None:
    _ensure_parent()
    tmp = _CONFIG_PATH.with_suffix(_CONFIG_PATH.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_CONFIG_PATH)
    except Exception as exc:
        logger.warning("写入渠道配置失败: %s", exc)


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
        return dict(_read_disk().get(channel_type) or {})


def get_field(channel_type: str, key: str, default: str = "") -> str:
    """获取某渠道某字段的配置值（env > JSON > default）。"""
    import os as _os

    for prefix in _env_prefixes(channel_type):
        for suffix in _env_suffixes(channel_type, key):
            env_val = _os.environ.get(f"KELLAI_{prefix}_{suffix}", "").strip()
            if env_val:
                return env_val
    cfg = get(channel_type)
    val = _saved_config(cfg).get(key)
    return str(val) if val is not None else default


def get_all(channel_type: str) -> dict[str, Any]:
    """获取渠道全量配置（含 env 默认）。"""
    cfg = get(channel_type)
    out = dict(cfg)
    merged_config = _saved_config(cfg)
    # env 默认值以"未在前端设置过"为判断标准
    for key in _expected_fields(channel_type):
        if key in merged_config and merged_config[key]:
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
        "phone": ["line"],
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
        all_cfg = _read_disk()
        cur = dict(all_cfg.get(channel_type) or {})
        # 合并：保留原 name/enabled，只覆盖 config
        new_cfg = dict(cur)
        incoming_config = dict(config or {})
        merged_config = dict(cur.get("config") or {})
        merged_config.update(incoming_config)
        new_cfg["config"] = merged_config
        if name is not None:
            new_cfg["name"] = str(name)
        if enabled is not None:
            new_cfg["enabled"] = bool(enabled)
        if connected is not None:
            new_cfg["connected"] = bool(connected)
        elif incoming_config:
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
        all_cfg = _read_disk()
        if channel_type not in all_cfg:
            return False
        all_cfg.pop(channel_type)
        _write_disk(all_cfg)
        return True


def list_all() -> dict[str, dict[str, Any]]:
    """列出所有已保存的渠道配置。"""
    with _LOCK:
        return dict(_read_disk())
