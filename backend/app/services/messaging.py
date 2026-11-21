"""Tenant/recipient authorization around the existing delivery ledger.

Both the desktop UI and the scoped XCMAX gateway use this boundary. Provider
credentials and native execution receipts never come from the agent gateway.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from app.channels.base import UnifiedMessage
from app.services import outbound_delivery
from app.services.tenant_context import resolve_team_id, tenant_scope


def require_actor(user: dict | None, *, manage: bool = False, read: bool = False) -> dict:
    if not user or int(user.get("id") or 0) <= 0 or int(user.get("team_id") or 0) <= 0:
        raise HTTPException(status_code=401, detail="请先登录有团队归属的客来来账号")
    roles = {"owner", "admin"} if manage else {"owner", "admin", "sales"}
    if read:
        roles.add("readonly")
    if user.get("role") not in roles:
        raise HTTPException(status_code=403, detail="当前账号没有此操作权限")
    resolve_team_id(int(user["team_id"]), required=True)
    return user


def request_actor(request: Request | None, **kwargs: Any) -> dict:
    return require_actor(getattr(getattr(request, "state", None), "user", None), **kwargs)


def _recipient(customer_id: int, channel_type: str, contact_id: str) -> str:
    """Require a persisted identity in this tenant, never resolve by display name."""
    from app.services.message_store import get_messages
    from app.services.pipeline import _customer_id_from_doc, _iter_pipeline_docs

    customer = next((doc for doc in _iter_pipeline_docs()
                     if _customer_id_from_doc(doc) == customer_id), None)
    if customer is None:
        raise HTTPException(status_code=404, detail="当前租户不存在此客户")
    if customer.get("is_demo"):
        raise HTTPException(status_code=409, detail="演示客户不能发送外部消息")
    contacts = customer.get("channel_contacts") or {}
    if isinstance(contacts, dict) and str(contacts.get(channel_type) or "") == contact_id:
        return str(customer.get("name") or customer.get("username") or contact_id)
    for message in get_messages(customer_id, channel_type, limit=500):
        if message.contact_id == contact_id:
            return message.contact_name or contact_id
    raise HTTPException(status_code=409, detail="客户未绑定此渠道的联系人标识，请先同步或绑定联系人")


def _message(body: Any, user: dict) -> UnifiedMessage:
    name = _recipient(body.customer_id, body.channel_type, body.contact_id)
    return UnifiedMessage(
        id="", customer_id=body.customer_id, channel_type=body.channel_type,
        contact_id=body.contact_id, contact_name=name, direction="outbound",
        content=body.content, content_type="text",
        metadata={
            "team_id": int(user["team_id"]),
            # Worker changes must not change the identity of the same auto job.
            "agent_user_id": 0 if body.auto_reply_inbound_id else int(user["id"]),
            "auto_reply_inbound_id": body.auto_reply_inbound_id,
        },
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _check_auto_lease(body: Any, team_id: int) -> None:
    if not body.auto_reply_inbound_id:
        return
    from app.services.auto_reply_runtime import begin_delivery

    if body.client_request_id != f"auto:{body.auto_reply_inbound_id}" or not begin_delivery(
        body.auto_reply_inbound_id, lease_token=body.auto_reply_lease_token,
        team_id=team_id, customer_id=body.customer_id, channel_type=body.channel_type,
        contact_id=body.contact_id, content=body.content,
    ):
        raise HTTPException(status_code=409, detail="自动回复租约失效或发送内容与任务不符")


def _desktop_request(request: Request | None, body: Any) -> None:
    host = str(getattr(getattr(request, "client", None), "host", ""))
    header = request.headers.get("X-Kellai-Desktop-Delivery") if request is not None else ""
    if body.channel_type != "douyin" or host not in {"127.0.0.1", "::1", "localhost"} or header != "1":
        raise HTTPException(status_code=403, detail="此执行方式仅限本机已登录的客来来桌面端")


def _channel(channel_type: str):
    from app.channels import ChannelRegistry
    from app.channels.config_store import get_all

    registry = ChannelRegistry()
    row = next((row for row in registry.list_channels() if row["channel_type"] == channel_type), None)
    if row is None:
        raise HTTPException(status_code=404, detail="未注册的渠道")
    if not (row.get("capabilities") or {}).get("send"):
        raise HTTPException(status_code=409, detail="此渠道尚无可用的发信实现")
    message_types = (row.get("capabilities") or {}).get("message_types")
    if message_types and "text" not in message_types:
        raise HTTPException(status_code=409, detail="此渠道仅支持模板通知，不能发送自由文本")
    config = get_all(channel_type)
    if config.get("enabled") is False:
        raise HTTPException(status_code=409, detail="此渠道未启用")
    return registry.get(channel_type), row.get("capabilities") or {}


def _envelope(receipt: dict) -> dict:
    return {"success": bool(receipt.get("success")), "data": receipt,
            "error": str(receipt.get("error") or "")}


def prepare_desktop(body: Any, request: Request) -> dict:
    user = request_actor(request)
    _desktop_request(request, body)
    if body.desktop_result is not None or body.delivery_token:
        raise HTTPException(status_code=422, detail="准备发送时不能提交执行回执")
    team_id = int(user["team_id"])
    with tenant_scope(team_id):
        _channel(body.channel_type)
        message = _message(body, user)
        _check_auto_lease(body, team_id)
        try:
            receipt = outbound_delivery.prepare_external(
                message, idempotency_key=body.client_request_id, team_id=team_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "data": receipt}


async def send(body: Any, *, user: dict, request: Request | None = None, native_allowed: bool = True) -> dict:
    user = require_actor(user, read=body.desktop_result is not None)
    team_id = int(user["team_id"])
    with tenant_scope(team_id):
        try:
            if body.desktop_result is not None:
                if not native_allowed:
                    raise HTTPException(status_code=403, detail="代理接口不接受桌面执行回执")
                _desktop_request(request, body)
                result = dict(body.desktop_result)
                if (result.get("source") != "douyin_desktop_automation"
                    or str(result.get("contact_id") or "") != body.contact_id
                    or (result.get("success") is True and result.get("message_sent") is not True)):
                    raise HTTPException(status_code=422, detail="无效的桌面执行回执")
                if not outbound_delivery.delivery_matches(
                    body.client_request_id, team_id=team_id, customer_id=body.customer_id,
                    channel_type=body.channel_type, contact_id=body.contact_id,
                    content=body.content, auto_reply_inbound_id=body.auto_reply_inbound_id,
                ):
                    raise HTTPException(status_code=409, detail="回执与原发送请求不符")
                receipt = outbound_delivery.complete_external(
                    idempotency_key=body.client_request_id, delivery_token=body.delivery_token,
                    result=result, team_id=team_id,
                )
            else:
                from app.channels.capabilities import resolve_send_capability
                adapter, capabilities = _channel(body.channel_type)
                message = _message(body, user)
                capabilities = resolve_send_capability(
                    body.channel_type, contact_id=body.contact_id, customer_id=body.customer_id,
                    contact_name=message.contact_name, team_id=team_id,
                )
                if capabilities.get("transport") == "desktop":
                    raise HTTPException(status_code=409, detail="requires_desktop_execution")
                _check_auto_lease(body, team_id)
                receipt = await outbound_delivery.dispatch(
                    message, idempotency_key=body.client_request_id, team_id=team_id,
                    sender=lambda: adapter.send_message(
                        body.contact_id, body.content, team_id=team_id,
                        customer_id=body.customer_id, contact_name=message.contact_name,
                        idempotency_key=body.client_request_id,
                    ),
                )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if body.auto_reply_inbound_id:
            from app.services.auto_reply_runtime import complete_job
            complete_job(
                body.auto_reply_inbound_id, success=bool(receipt.get("success")),
                error=str(receipt.get("error") or ""), outbound_message_id=receipt.get("message_id", ""),
                team_id=team_id, lease_token=body.auto_reply_lease_token,
                delivery_key=body.client_request_id,
            )
    return _envelope(receipt)


def receipt(request_id: str, *, user: dict) -> dict:
    user = require_actor(user, read=True)
    try:
        result = outbound_delivery.get_delivery(request_id, team_id=int(user["team_id"]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="发送请求不存在")
    return {"success": True, "data": result}


async def send_douyin_bridge(body: Any) -> dict:
    """Called only after the service bridge key has been authenticated.

    Desktop customer IDs are local to their database. Resolve the cloud-side
    customer from its stable channel identity instead of reusing that number.
    """
    from app.channels.douyin import DouyinAdapter
    from app.channels.capabilities import resolve_send_capability
    from app.services.growth_loop import resolve_customer_for_message
    from app.services.pipeline import save_pipeline

    team_id = int(body.team_id)
    with tenant_scope(team_id):
        capabilities = resolve_send_capability("douyin", contact_id=body.contact_id, team_id=team_id)
        if capabilities.get("requires_desktop_execution"):
            raise HTTPException(status_code=409, detail="requires_desktop_execution")
        message = UnifiedMessage(
            id="", customer_id=0, channel_type="douyin", contact_id=body.contact_id,
            contact_name=body.contact_id, direction="outbound", content=body.content,
            metadata={"team_id": team_id, "source": "authenticated_douyin_bridge",
                      "client_customer_id": body.customer_id, "persona_id": body.persona_id,
                      "reply_context": body.reply_context},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        customer = resolve_customer_for_message(message)
        save_pipeline(customer)
        message = message.model_copy(update={"customer_id": int(customer["customer_id"])})
        try:
            result = await outbound_delivery.dispatch(
                message, idempotency_key=body.client_request_id, team_id=team_id,
                sender=lambda: DouyinAdapter().send_message(
                    body.contact_id, body.content, team_id=team_id, persona_id=body.persona_id,
                    customer_id=int(customer["customer_id"]), reply_context=body.reply_context,
                    idempotency_key=body.client_request_id, _bridge_local_execution=True,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    data = {**result.get("channel_result", {}), "success": result["success"],
            "message_id": result["provider_message_id"], "delivery_state": result["provider_state"],
            "receipt": result}
    return {"success": result["success"], "data": data, "error": result.get("error", "")}
