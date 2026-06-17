"""渠道适配器注册中心（单例）。"""

from __future__ import annotations

import logging
from typing import Any

from app.channels.base import ChannelAdapter

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
            cls._instance._instances: dict[str, ChannelAdapter] = {}
        return cls._instance

    def register(
        self,
        channel_type: str,
        adapter_class: type[ChannelAdapter],
        config_schema: dict | None = None,
    ) -> None:
        """注册一个渠道适配器。"""
        self._registry[channel_type] = {
            "adapter_class": adapter_class,
            "config_schema": config_schema or {},
        }
        logger.info("渠道已注册: %s", channel_type)

    def get(self, channel_type: str) -> ChannelAdapter:
        """获取渠道适配器实例（缓存，只实例化一次）。"""
        resolved_type = self._aliases.get(channel_type, channel_type)
        if resolved_type not in self._registry:
            raise KeyError(f"未注册的渠道类型: {channel_type}")
        if resolved_type not in self._instances:
            adapter_class = self._registry[resolved_type]["adapter_class"]
            self._instances[resolved_type] = adapter_class()
        return self._instances[resolved_type]

    def list_channels(self) -> list[dict[str, Any]]:
        """列出所有已注册渠道信息。"""
        result: list[dict[str, Any]] = []
        for channel_type, info in self._registry.items():
            result.append({
                "channel_type": channel_type,
                "adapter_class": info["adapter_class"].__name__,
                "config_schema": info["config_schema"],
            })
        return result
