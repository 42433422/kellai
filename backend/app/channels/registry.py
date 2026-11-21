"""渠道适配器注册中心（单例）。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from app.channels.base import ChannelAdapter
from app.channels import config_store
from app.services.tenant_context import current_team_id

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """管理渠道适配器的注册与获取（单例）。"""

    _instance: ChannelRegistry | None = None
    _aliases: dict[str, str] = {
        "wecom": "wework",
        "miniapp": "miniprogram",
    }

    def __new__(cls) -> ChannelRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._registry: dict[str, dict[str, Any]] = {}
            cls._instance._instances: dict[tuple[int, str], tuple[str, ChannelAdapter]] = {}
            cls._instance._retired: list[ChannelAdapter] = []
        return cls._instance

    def register(
        self,
        channel_type: str,
        adapter_class: type[ChannelAdapter],
        config_schema: dict | None = None,
        capabilities: dict | None = None,
    ) -> None:
        """注册一个渠道适配器。"""
        self._registry[channel_type] = {
            "adapter_class": adapter_class,
            "config_schema": config_schema or {},
            "capabilities": capabilities or {
                "receive": False, "send": False, "contacts": False, "sync": False,
                "transport": "unverified", "receive_mode": "none", "readiness": "unverified",
            },
        }
        logger.info("渠道已注册: %s", channel_type)

    def get(self, channel_type: str) -> ChannelAdapter:
        """获取当前租户、当前配置版本的适配器实例。"""
        resolved_type = self._aliases.get(channel_type, channel_type)
        if resolved_type not in self._registry:
            raise KeyError(f"未注册的渠道类型: {channel_type}")
        key = (current_team_id(), resolved_type)
        fingerprint = hashlib.sha256(json.dumps(config_store.get_all(resolved_type), sort_keys=True,
                                               default=str).encode()).hexdigest()
        cached = self._instances.get(key)
        if cached is None or cached[0] != fingerprint:
            if cached is not None:
                # Keep in-flight calls alive; retired clients are drained at shutdown.
                self._retired.append(cached[1])
            adapter_class = self._registry[resolved_type]["adapter_class"]
            self._instances[key] = (fingerprint, adapter_class())
        return self._instances[key][1]

    async def invalidate(self, channel_type: str | None = None) -> None:
        """Invalidate only the current tenant's adapters after configuration edits."""
        resolved = self._aliases.get(channel_type, channel_type) if channel_type else None
        keys = [key for key in self._instances
                if key[0] == current_team_id() and (resolved is None or key[1] == resolved)]
        for key in keys:
            self._retired.append(self._instances.pop(key)[1])

    async def close_all(self) -> None:
        adapters = [value[1] for value in self._instances.values()] + self._retired
        self._instances.clear()
        self._retired.clear()
        await asyncio.gather(*(adapter.close() for adapter in adapters), return_exceptions=True)

    def list_channels(self) -> list[dict[str, Any]]:
        """列出所有已注册渠道信息。"""
        result: list[dict[str, Any]] = []
        for channel_type, info in self._registry.items():
            capabilities = dict(info["capabilities"])
            if channel_type == "phone":
                from app.channels.phone import phone_capabilities
                capabilities = phone_capabilities(capabilities)
            result.append({
                "channel_type": channel_type,
                "adapter_class": info["adapter_class"].__name__,
                "config_schema": info["config_schema"],
                "capabilities": capabilities,
            })
        return result
