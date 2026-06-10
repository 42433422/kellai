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


def get(channel_type: str) -> dict[str, Any]:
    """获取某渠道的已保存配置（不含 env 兜底）。"""
    with _LOCK:
        return dict(_read_disk().get(channel_type) or {})


def get_field(channel_type: str, key: str, default: str = "") -> str:
    """获取某渠道某字段的配置值（env > JSON > default）。"""
    import os as _os

    env_val = _os.environ.get(f"KELLAI_{channel_type.upper()}_{key.upper()}", "").strip()
    if env_val:
        return env_val
    cfg = get(channel_type)
    val = cfg.get(key)
    return str(val) if val is not None else default


def get_all(channel_type: str) -> dict[str, Any]:
    """获取渠道全量配置（含 env 默认）。"""
    cfg = get(channel_type)
    out = dict(cfg)
    # env 默认值以"未在前端设置过"为判断标准
    for key in _expected_fields(channel_type):
        if key in out and out[key]:
            continue
        env_val = os.environ.get(f"KELLAI_{channel_type.upper()}_{key.upper()}", "").strip()
        if env_val:
            out.setdefault(key, env_val)
    return out


def _expected_fields(channel_type: str) -> list[str]:
    """前端可能配置的所有字段名（key 集合）。"""
    map_: dict[str, list[str]] = {
        "wework": ["corp_id", "secret", "agent_id", "bot_webhook"],
        "wecom": ["corp_id", "secret", "agent_id", "bot_webhook"],
        "douyin": ["app_id", "app_secret"],
        "miniprogram": ["app_id", "app_secret", "template_id"],
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
         enabled: Optional[bool] = None) -> dict[str, Any]:
    """保存渠道配置。

    写回磁盘并返回该渠道的最终状态 dict（含 name/enabled/connected）。
    """
    with _LOCK:
        all_cfg = _read_disk()
        cur = dict(all_cfg.get(channel_type) or {})
        # 合并：保留原 name/enabled，只覆盖 config
        new_cfg = dict(cur)
        new_cfg["config"] = dict(config or {})
        if name is not None:
            new_cfg["name"] = str(name)
        if enabled is not None:
            new_cfg["enabled"] = bool(enabled)
        new_cfg.setdefault("name", channel_type)
        new_cfg.setdefault("enabled", False)
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
