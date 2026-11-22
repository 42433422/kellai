"""Local account tool UI: connection management, visual inbox and receipts."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.services.messaging import request_actor

router = APIRouter(prefix="/api/kellai", tags=["account-tool"])


class XcmaxAuthorizeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=200)
    accepted_scopes: list[str]


class XcmaxCancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=200)


class SyncBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=50, ge=1, le=500)


class ContactBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(min_length=1, max_length=128)
    contact_id: str = Field(min_length=1, max_length=256)
    contact_name: str = Field(default="", max_length=256)


def _account(connection_id: str) -> dict:
    from app.channels.config_store import get_connection
    try:
        return get_connection(connection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="账号连接不存在") from exc


def _require_xcmax_loopback(request: Request) -> str:
    from app.services.auth import require_local_request
    require_local_request(request)
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else ""


@router.get("/status")
def status():
    return {"success": True, "data": {"product": "客来来账号与通道工具", "protocol_version": 2, "mode": "local_tool"}}


@router.post("/auth/xcmax-desktop")
def auth_xcmax_desktop(request: Request):
    from app.services.auth import require_local_request
    from app.services.xcmax_integration import create_desktop_login_for_pending_pairing
    require_local_request(request, header="X-Kellai-Desktop-Handoff")
    try:
        return create_desktop_login_for_pending_pairing()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/integrations/xcmax/status")
def xcmax_integration_status(request: Request):
    from app.services.xcmax_integration import public_status
    request_actor(request, read=True)
    return {"success": True, "data": public_status()}


@router.get("/integrations/xcmax/pending")
def xcmax_integration_pending(request: Request):
    from app.services.xcmax_integration import pending_authorization
    request_actor(request, manage=True)
    return {"success": True, "data": pending_authorization()}


@router.post("/integrations/xcmax/approve")
def xcmax_integration_approve(body: XcmaxAuthorizeBody, request: Request):
    from app.services.xcmax_integration import approve_authorization
    user = request_actor(request, manage=True)
    try:
        return {"success": True, "data": approve_authorization(**body.model_dump(), current_user=user)}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/integrations/xcmax/cancel")
def xcmax_integration_cancel(body: XcmaxCancelBody, request: Request):
    from app.services.xcmax_integration import cancel_authorization
    request_actor(request, manage=True)
    try:
        cancel_authorization(**body.model_dump())
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True}


@router.post("/integrations/xcmax/disconnect")
def xcmax_integration_disconnect(request: Request):
    from app.services.xcmax_integration import disconnect
    request_actor(request, manage=True)
    return {"success": True, "data": disconnect()}


@router.get("/channels")
def list_channels(request: Request):
    from app.channels import ChannelRegistry
    request_actor(request, read=True)
    return {"success": True, "data": ChannelRegistry().list_channels()}


@router.post("/channels/sync-inbox")
async def sync_channel_inbox(body: SyncBody, request: Request):
    from app.services.channel_ingest import sync_inbox
    request_actor(request, manage=True)
    _account(body.connection_id)
    return await sync_inbox(**body.model_dump())


def contacts_payload(connection_id: str = "", limit: int = 500) -> dict:
    from app.services.message_store import list_contacts, migrate_account_bindings
    from app.services.outbound_delivery import ensure_schema
    if connection_id:
        _account(connection_id)
    ensure_schema()
    migrate_account_bindings()
    rows = list_contacts(connection_id=connection_id, limit=limit)
    return {"success": True, "data": {"contacts": rows, "total": len(rows)}}


@router.get("/contacts")
def contacts(request: Request, connection_id: str = "", limit: int = Query(500, ge=1, le=500)):
    request_actor(request, read=True)
    return contacts_payload(connection_id, limit)


@router.post("/contacts")
def add_contact(body: ContactBody, request: Request):
    from app.channels.config_store import connection_scope
    from app.services.message_store import register_contact
    request_actor(request, manage=True)
    account = _account(body.connection_id)
    if not account.get("enabled"):
        raise HTTPException(status_code=409, detail="账号连接已停用")
    with connection_scope(body.connection_id):
        contact = register_contact(**body.model_dump(), channel_type=account["channel_type"])
    return {"success": True, "data": contact}


def messages_payload(customer_id: int, connection_id: str, *, limit: int = 100, message_id: str | None = None) -> dict:
    from app.services.message_store import get_messages_with_state
    _account(connection_id)  # Identity tombstones preserve history after credential deletion.
    rows = get_messages_with_state(customer_id, connection_id=connection_id, limit=limit, message_id=message_id)
    return {"success": True, "data": {"customer_id": customer_id, "connection_id": connection_id,
                                      "messages": rows, "total": len(rows)}}


@router.get("/contacts/{customer_id}/messages")
def contact_messages(customer_id: int, request: Request, connection_id: str = Query(min_length=1, max_length=128),
                     limit: int = Query(100, ge=1, le=500), message_id: str | None = None):
    request_actor(request, read=True)
    return messages_payload(customer_id, connection_id, limit=limit, message_id=message_id)


@router.get("/messages/requests/{client_request_id}")
def message_delivery_receipt(client_request_id: str, request: Request):
    from app.services.messaging import receipt
    return receipt(client_request_id, user=request_actor(request, read=True))
