"""Explicitly scoped local channel access for the installed XCMAX module."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.services.tenant_context import tenant_scope

router = APIRouter(prefix="/api/kellai/integrations/xcmax", tags=["xcmax"])


class SendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: int = Field(gt=0)
    channel_type: str = Field(min_length=1, max_length=32)
    contact_id: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=8000)
    client_request_id: str = Field(min_length=1, max_length=200)


def _connection(request: Request, scope: str) -> dict:
    from app.api.routes import _require_xcmax_loopback
    from app.services.xcmax_integration import authorize_access_token
    return authorize_access_token(_require_xcmax_loopback(request), scope)


@router.get("/channels")
async def channels(request: Request):
    from app.api.routes import list_channels
    connection = _connection(request, "channels.read")
    with tenant_scope(int(connection["team_id"])):
        response = await list_channels()
    return {"success": True, "data": {"channels": response["data"]}}


@router.post("/messages/send")
async def send_message(body: SendBody, request: Request):
    from app.api.routes import ChannelSendMessageBody
    from app.services.messaging import send
    connection = _connection(request, "messages.send")
    with tenant_scope(int(connection["team_id"])):
        return await send(ChannelSendMessageBody(**body.model_dump()),
                          user=connection["actor"], native_allowed=False)


@router.get("/messages/requests/{client_request_id}")
def message_receipt(client_request_id: str, request: Request):
    from app.services.messaging import receipt
    connection = _connection(request, "messages.send")
    with tenant_scope(int(connection["team_id"])):
        return receipt(client_request_id, user=connection["actor"])
