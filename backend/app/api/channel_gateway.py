"""Provider-signed callbacks. User JWT is not the authentication mechanism here."""
from fastapi import APIRouter, HTTPException, Request

from app.channels.chatwoot import ChatwootSettings
from app.services.chatwoot_gateway import MAX_WEBHOOK_BYTES, WebhookRejected, authenticate, store_event
from app.services.tenant_context import tenant_scope

router = APIRouter()


@router.post("/api/kellai/webhook/chatwoot/{team_id}")
async def chatwoot_webhook(team_id: int, request: Request) -> dict:
    if team_id <= 0:
        raise HTTPException(status_code=404, detail="团队不存在")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="Chatwoot 回调过大")
    with tenant_scope(team_id):
        try:
            settings = ChatwootSettings.load()
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Chatwoot 回调未配置") from exc
        try:
            signature = request.headers.get("x-chatwoot-signature", "")
            payload = authenticate(bytes(raw), timestamp=request.headers.get("x-chatwoot-timestamp", ""),
                                   signature=signature, settings=settings)
            result = store_event(payload, settings=settings, team_id=team_id,
                                 delivery_id=request.headers.get("x-chatwoot-delivery") or signature)
        except WebhookRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if result.get("kind") in {"inbound", "receipt"}:
            from app.services.channel_ingest import sync_inbox
            # Durable inbox insert precedes scheduling. Failed sync remains available
            # to the existing worker; acknowledging a webhook never discards it.
            await sync_inbox(team_id=team_id, channel_type="chatwoot")
        return result
