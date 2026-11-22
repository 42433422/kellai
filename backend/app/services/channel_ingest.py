"""The sole inbox consumer persists messages; XCMAX owns business processing."""
from __future__ import annotations

from app.services.tenant_context import resolve_team_id, tenant_scope


async def sync_inbox(*, team_id: int = 0, connection_id: str, limit: int = 50) -> dict:
    from app.channels import ChannelRegistry
    from app.channels.config_store import connection_scope, get_connection
    from app.services.message_store import mark_inbox_consumed, save_message

    tid = resolve_team_id(team_id, required=True)
    saved = []
    with tenant_scope(tid), connection_scope(connection_id):
        account = get_connection(connection_id)
        if not account.get("enabled"):
            return {"success": False, "error": "账号连接已停用", "data": {"synced": 0, "consumed": 0}}
        adapter = ChannelRegistry().get(account["channel_type"], connection_id=connection_id)
        messages = await adapter.receive_messages(limit=limit)
        for msg in messages:
            metadata = dict(msg.metadata or {})
            if int(metadata.get("team_id") or tid) != tid:
                raise PermissionError("回调工作区与连接不一致")
            if msg.connection_id and msg.connection_id != connection_id:
                raise PermissionError("回调账号与连接不一致")
            if metadata.get("connection_id") and metadata["connection_id"] != connection_id:
                raise PermissionError("回调账号与连接不一致")
            if msg.channel_type != account["channel_type"]:
                raise PermissionError("回调渠道与连接不一致")
            metadata.update(team_id=tid, connection_id=connection_id)
            item = save_message(msg.model_copy(update={"connection_id": connection_id, "metadata": metadata}))
            saved.append(item.model_dump())
        consumed = mark_inbox_consumed([msg.id for msg in messages], team_id=tid, connection_id=connection_id)
    return {"success": True, "data": {"synced": len(saved), "consumed": consumed, "messages": saved}}
