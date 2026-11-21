"""One inbox consumer shared by callbacks, the desktop and the API worker."""

from __future__ import annotations

import logging
from typing import Any

from app.services.tenant_context import resolve_team_id, tenant_scope

logger = logging.getLogger(__name__)


async def sync_inbox(*, team_id: int = 0, channel_type: str = "", limit: int = 50) -> dict:
    from app.channels import ChannelRegistry
    from app.services.auto_reply_runtime import enqueue_message
    from app.services.message_store import mark_inbox_consumed, save_message

    team_id = resolve_team_id(team_id)
    registry = ChannelRegistry()
    types = [channel_type] if channel_type else [c["channel_type"] for c in registry.list_channels()]
    saved_messages: list[dict[str, Any]] = []
    consumed = queued = 0
    relay_channels: list[str] = []
    errors: list[dict[str, str]] = []
    # Signed callbacks and the worker always pass an explicit positive tenant.
    # The zero branch is retained only for the legacy local migration helpers.
    from contextlib import nullcontext
    with tenant_scope(team_id) if team_id else nullcontext():
        for kind in types:
            if kind == "douyin":
                from app.services.douyin_channel import bridge_server_enabled
                if bridge_server_enabled():
                    # The bridge is a relay, and the authenticated desktop pull
                    # owns this consumed cursor. Manual sync must not steal it.
                    relay_channels.append(kind)
                    continue
            if kind == "chatwoot" and not channel_type:
                from app.channels.config_store import get_all
                if not get_all(kind).get("enabled"):
                    continue
            local_ids: list[str] = []
            remote = False
            try:
                adapter = registry.get(kind)
                if kind == "douyin":
                    from app.services.douyin_channel import remote_bridge_enabled
                    remote = remote_bridge_enabled()
                    messages = await adapter.receive_messages(limit=limit, team_id=team_id)
                else:
                    messages = await adapter.receive_messages(limit=limit)
            except Exception:
                logger.exception("渠道收件箱读取失败: channel=%s team=%s", kind, team_id)
                errors.append({"channel_type": kind, "error": "收件箱读取失败，请检查连接状态"})
                continue
            for message in messages:
                try:
                    metadata = dict(message.metadata or {})
                    if int(metadata.get("team_id") or team_id) != team_id:
                        raise ValueError("inbox_tenant_mismatch")
                    metadata["team_id"] = team_id
                    message = message.model_copy(update={"metadata": metadata})
                    saved = save_message(message)
                    # An enqueue failure must leave the inbox replayable.
                    if team_id > 0:
                        queued += int(enqueue_message(saved))
                    saved_messages.append(saved.model_dump())
                    local_ids.append(message.id)
                except Exception:
                    logger.exception("消息接入未完成: channel=%s message_id=%s", kind, message.id)
                    errors.append({"channel_type": kind, "error": f"消息 {message.id} 接入失败，已保留待重试"})
            try:
                if remote and local_ids:
                    from app.services.douyin_channel import remote_ack_inbox
                    consumed += await remote_ack_inbox(team_id, local_ids)
                else:
                    consumed += mark_inbox_consumed(local_ids, team_id=team_id)
            except Exception:
                logger.exception("渠道接入确认失败: channel=%s", kind)
                errors.append({"channel_type": kind, "error": "消息已落库，接入确认待重试"})
    return {"success": not errors, "data": {
        "synced": len(saved_messages), "consumed": consumed, "messages": saved_messages,
        "auto_reply_queued": queued, "errors": errors, "partial": bool(errors and saved_messages),
        "relay_channels": relay_channels,
    }}
