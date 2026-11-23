"""Account/recipient authorization around the sole durable delivery ledger."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable

from fastapi import HTTPException, Request

from app.channels.base import UnifiedMessage
from app.services import outbound_delivery
from app.services.tenant_context import resolve_team_id, tenant_scope


def require_actor(user: dict | None, *, manage: bool = False, read: bool = False) -> dict:
    if not user or int(user.get("id") or 0) <= 0 or int(user.get("team_id") or 0) <= 0:
        raise HTTPException(status_code=401, detail="请从 XCMAX 打开账号工具")
    if user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="工具操作者身份无效")
    resolve_team_id(int(user["team_id"]), required=True)
    return user


def request_actor(request: Request | None, **kwargs: Any) -> dict:
    return require_actor(getattr(getattr(request, "state", None), "user", None), **kwargs)


def _recipient(body) -> dict:
    from app.services.message_store import get_contact
    contact = get_contact(body.customer_id, connection_id=body.connection_id,
                          channel_type=body.channel_type, contact_id=body.contact_id)
    if contact is None:
        raise HTTPException(status_code=409, detail="账号、渠道与联系人绑定不一致，请先同步或明确绑定联系人")
    if contact.get("is_demo"):
        raise HTTPException(status_code=409, detail="演示联系人不能发送外部消息")
    return contact


def _channel(body):
    from app.channels import ChannelRegistry
    from app.channels.config_store import get_connection
    try:
        account = get_connection(body.connection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="账号连接不存在") from exc
    if account["channel_type"] != body.channel_type:
        raise HTTPException(status_code=409, detail="账号连接与发送渠道不一致")
    if not account.get("enabled") or account.get("status") in {"revoked", "requires_reconnect", "executor_required", "deleted", "vault_locked"}:
        raise HTTPException(status_code=409, detail="账号连接已停用")
    registry = ChannelRegistry()
    row = next((r for r in registry.list_channels() if r["channel_type"] == body.channel_type), None)
    capability = (row or {}).get("capabilities") or {}
    if not capability.get("send") or capability.get("transport") not in {"api", "gateway", "sms_api"}:
        raise HTTPException(status_code=409, detail="此账号渠道没有已实现的 API 发送能力")
    if capability.get("message_types") and "text" not in capability["message_types"]:
        raise HTTPException(status_code=409, detail="此渠道仅支持模板通知")
    return registry.get(body.channel_type, connection_id=body.connection_id)


async def send(body, *, user: dict, before_send: Callable[[], Any]) -> dict:
    from app.channels.config_store import connection_scope
    user = require_actor(user)
    team_id = int(user["team_id"])
    from app.channels.config_store import get_connection
    try:
        get_connection(body.connection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="账号连接不存在") from exc
    with tenant_scope(team_id), connection_scope(body.connection_id):
        adapter = _channel(body)
        contact = _recipient(body)
        message = UnifiedMessage(id="", customer_id=body.customer_id,
            connection_id=body.connection_id, channel_type=body.channel_type,
            contact_id=body.contact_id, contact_name=contact["contact_name"], direction="outbound",
            content=body.content, metadata={"team_id": team_id, "connection_id": body.connection_id,
                "agent_user_id": int(user["id"])}, created_at=datetime.now(timezone.utc).isoformat())
        try:
            result = await outbound_delivery.dispatch(message, idempotency_key=body.client_request_id,
                team_id=team_id, sender=lambda: adapter.send_message(body.contact_id, body.content,
                    team_id=team_id, customer_id=body.customer_id, connection_id=body.connection_id,
                    contact_name=contact["contact_name"], idempotency_key=body.client_request_id,
                    before_send=before_send))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": bool(result.get("success")), "data": result, "error": str(result.get("error") or "")}


def receipt(request_id: str, *, user: dict) -> dict:
    user = require_actor(user, read=True)
    try:
        result = outbound_delivery.get_delivery(request_id, team_id=int(user["team_id"]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="发送请求不存在")
    return {"success": True, "data": result}
