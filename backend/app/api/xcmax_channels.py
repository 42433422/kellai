"""Scoped host gateway. The host is the sole business/approval execution entry."""
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.services.tenant_context import tenant_scope

router = APIRouter(prefix="/api/kellai/integrations/xcmax", tags=["xcmax"])


class SendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(min_length=1, max_length=128)
    customer_id: int = Field(gt=0)
    channel_type: str = Field(min_length=1, max_length=32)
    contact_id: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=8000)
    client_request_id: str = Field(min_length=1, max_length=200)


def _connection(request: Request, scope: str | None = None) -> dict:
    from app.api.routes import _require_xcmax_loopback
    from app.services.xcmax_integration import authorize_access_token
    return authorize_access_token(_require_xcmax_loopback(request), scope)


@router.get("/grant-status")
def grant_status(request: Request):
    connection = _connection(request)
    return {"success": True, "data": {"connection_id": connection["connection_id"],
        "protocol_version": connection["protocol_version"],
        "authorized_scopes": sorted(connection.get("authorized_scopes") or [])}}


@router.get("/channels")
def channels(request: Request):
    from app.channels import ChannelRegistry
    from app.channels.config_store import list_connections, connection_scope
    connection = _connection(request, "channels.read")
    rows = []
    with tenant_scope(connection["team_id"]):
        registry = ChannelRegistry()
        for account in list_connections():
            with connection_scope(account["connection_id"]):
                catalog = {r["channel_type"]: r for r in registry.list_channels()}
                capability = catalog.get(account["channel_type"], {}).get("capabilities", {})
            rows.append({"connection_id": account["connection_id"], "channel_type": account["channel_type"],
                         "name": account["name"], "enabled": account["enabled"],
                         "connected": bool(account.get("connected")), "capabilities": capability,
                         "status": account.get("status") or ("connected" if account.get("connected") else "configured")})
    return {"success": True, "data": {"channels": rows}}


@router.get("/contacts")
def contacts(request: Request, connection_id: str = "", limit: int = Query(500, ge=1, le=500)):
    from app.api.routes import contacts_payload
    connection = _connection(request, "messages.read")
    with tenant_scope(connection["team_id"]):
        return contacts_payload(connection_id, limit)


@router.get("/contacts/{customer_id}/messages")
def messages(customer_id: int, request: Request, connection_id: str = Query(min_length=1, max_length=128),
             limit: int = Query(100, ge=1, le=500), message_id: str | None = None):
    from app.api.routes import messages_payload
    connection = _connection(request, "messages.read")
    with tenant_scope(connection["team_id"]):
        return messages_payload(customer_id, connection_id, limit=limit, message_id=message_id)


@router.post("/messages/send")
async def send_message(body: SendBody, request: Request):
    from app.services.messaging import send
    connection = _connection(request, "messages.send")
    with tenant_scope(connection["team_id"]):
        return await send(body, user=connection["actor"], before_send=lambda: _connection(request, "messages.send"))


@router.get("/messages/requests/{client_request_id}")
def message_receipt(client_request_id: str, request: Request):
    from app.services.messaging import receipt
    connection = _connection(request, "messages.send")
    with tenant_scope(connection["team_id"]):
        return receipt(client_request_id, user=connection["actor"])
