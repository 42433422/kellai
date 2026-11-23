"""渠道适配器注册中心（单例）。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.channels.base import ChannelAdapter
from app.channels import config_store
from app.services.tenant_context import current_team_id, tenant_scope
from app.services.connection_store import require_active

logger = logging.getLogger(__name__)


class _BoundAdapter(ChannelAdapter):
    """Bind lazy adapter credential reads and inbox reads to one explicit account."""

    def __init__(self, adapter: ChannelAdapter, connection_id: str, owner_id: int, version: int):
        self._adapter = adapter
        self.connection_id = connection_id
        self.channel_type = adapter.channel_type
        self._owner_id = owner_id
        self._version = version
        self._inflight = 0
        self._retiring = False
        self._closed = False

    async def _invoke(self, method: str, *args, **kwargs):
        with tenant_scope(self._owner_id), config_store.connection_scope(self.connection_id):
            item = (config_store.get_connection(self.connection_id, include_secrets=True)
                    if method == "test_connection" else require_active(self.connection_id))
            if item["version"] != self._version:
                raise config_store.ConnectionConflict("账号配置已变化，请重新获取连接")
            if self._retiring:
                raise config_store.ConnectionConflict("账号连接实例已更新，请重新获取")
            if method == "send_message":
                host_guard = kwargs.get("before_send")

                def before_send(*, config_version: int | None = None):
                    current = require_active(self.connection_id, channel_type=self.channel_type)
                    expected = self._version if config_version is None else config_version
                    if current["version"] != expected or self._retiring:
                        raise config_store.ConnectionConflict("发送前账号配置已变化")
                    if host_guard is not None:
                        host_guard()

                kwargs["before_send"] = before_send
            self._inflight += 1
            try:
                return await getattr(self._adapter, method)(*args, **kwargs)
            finally:
                self._inflight -= 1
                if self._retiring and self._inflight == 0:
                    await self.close()

    async def send_message(self, contact_id: str, content: str, **kwargs):
        return await self._invoke("send_message", contact_id, content, **kwargs)

    async def receive_messages(self, since: str = "", limit: int = 50, **kwargs):
        return await self._invoke("receive_messages", since=since, limit=limit, **kwargs)

    async def get_contacts(self, keyword: str = "", limit: int = 80, **kwargs):
        return await self._invoke("get_contacts", keyword=keyword, limit=limit, **kwargs)

    async def test_connection(self, **kwargs):
        return await self._invoke("test_connection", **kwargs)

    async def close(self):
        if not self._closed:
            self._closed = True
            await self._adapter.close()

    async def retire(self):
        self._retiring = True
        if self._inflight == 0:
            await self.close()


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
            cls._instance._cleanup_tasks: set[asyncio.Task] = set()
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

    def get(self, channel_type: str, connection_id: str | None = None) -> ChannelAdapter:
        """获取当前租户、当前配置版本的适配器实例。"""
        resolved_type = self._aliases.get(channel_type, channel_type)
        if resolved_type not in self._registry:
            raise KeyError(f"未注册的渠道类型: {channel_type}")
        identifier = connection_id or config_store.current_connection_id(required=True)
        item = config_store.get_connection(identifier, include_secrets=True)
        if item["channel_type"] != resolved_type:
            raise PermissionError("账号连接与渠道不匹配")
        key = (current_team_id(), identifier)
        fingerprint = item["version"]
        cached = self._instances.get(key)
        if cached is None or cached[0] != fingerprint:
            if cached is not None:
                # Keep in-flight calls alive; retired clients are drained at shutdown.
                self._retire(cached[1])
            adapter_class = self._registry[resolved_type]["adapter_class"]
            with config_store.connection_scope(identifier):
                adapter = adapter_class()
            self._instances[key] = (fingerprint, _BoundAdapter(adapter, identifier, key[0], fingerprint))
        return self._instances[key][1]

    def _retire(self, adapter: _BoundAdapter) -> None:
        try:
            task = asyncio.get_running_loop().create_task(adapter.retire())
        except RuntimeError:
            self._retired.append(adapter)
        else:
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)

    async def invalidate(self, channel_type: str | None = None, connection_id: str | None = None) -> None:
        """Invalidate only the current tenant's adapters after configuration edits."""
        resolved = self._aliases.get(channel_type, channel_type) if channel_type else None
        keys = [key for key, value in self._instances.items()
                if key[0] == current_team_id()
                and (connection_id is None or key[1] == connection_id)
                and (resolved is None or value[1].channel_type == resolved)]
        for key in keys:
            await self._instances.pop(key)[1].retire()

    async def close_all(self) -> None:
        adapters = [value[1] for value in self._instances.values()] + self._retired
        self._instances.clear()
        self._retired.clear()
        await asyncio.gather(*(adapter.close() for adapter in adapters), return_exceptions=True)
        if self._cleanup_tasks:
            await asyncio.gather(*list(self._cleanup_tasks), return_exceptions=True)

    def list_channels(self) -> list[dict[str, Any]]:
        """列出所有已注册渠道信息。"""
        result: list[dict[str, Any]] = []
        for channel_type, info in self._registry.items():
            capabilities = dict(info["capabilities"])
            if (channel_type == "phone" and config_store.current_connection_id()
                    and config_store.get_connection(config_store.current_connection_id())["channel_type"] == "phone"):
                from app.channels.phone import phone_capabilities
                capabilities = phone_capabilities(capabilities)
            result.append({
                "channel_type": channel_type,
                "adapter_class": info["adapter_class"].__name__,
                "config_schema": info["config_schema"] or config_store.config_schema(channel_type),
                "auth_types": ["oauth2"] if channel_type == "oauth2" else
                              ["credentials", "oauth2"] if channel_type == "douyin" else ["credentials"],
                "capabilities": capabilities,
            })
        return result
