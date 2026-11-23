"""Recover the same accepted provider message, without issuing a second POST."""
import json
import sqlite3
import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.channels import ChannelRegistry, config_store
from app.channels.base import UnifiedMessage
from app.services import message_store, outbound_delivery
from app.services.chatwoot_gateway import RECEIPT_CHANNEL, reconcile_pending_receipts, store_event
from app.services.tenant_context import tenant_scope


async def interrupted_delivery():
    config = {"base_url": "https://gateway.example", "account_id": "7", "inbox_id": "11",
              "api_access_token": "isolated-token", "webhook_secret": "isolated-hook"}
    config_store.create_connection("chatwoot", config, connection_id="original-account")
    original = ChannelRegistry().get("chatwoot", "original-account")
    settings = original._adapter.settings()
    remote = {"id": 81, "inbox_id": 11, "conversation_id": 23, "message_type": 1,
              "private": False, "status": "delivered", "content": "original approved text",
              "content_attributes": {"kellai_request_id": "original-request"}}
    calls = []

    def provider(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer isolated-token"
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["content"] == remote["content"]
            assert payload["content_attributes"]["kellai_request_id"] == "original-request"
            # The provider committed message 81; its response is lost.
            raise httpx.ReadTimeout("accepted response lost", request=request)
        if request.url.path.endswith("/messages"):
            assert dict(request.url.params) == {"after": "81", "before": "82"}
            return httpx.Response(200, json={"payload": [dict(remote)]})
        return httpx.Response(200, json={"id": 23, "inbox_id": 11, "can_reply": True})

    async def attach(adapter):
        old = await adapter._adapter._get_client()
        replacement = httpx.AsyncClient(base_url=old.base_url, headers=old.headers,
                                        transport=httpx.MockTransport(provider))
        await old.aclose()
        adapter._adapter._client = replacement

    await attach(original)
    message = UnifiedMessage(id="", customer_id=7, connection_id="original-account", channel_type="chatwoot",
        contact_id=settings.target(23), contact_name="Original recipient", content=remote["content"],
        direction="outbound", metadata={"team_id": 1}, created_at=datetime.now(timezone.utc).isoformat())
    first = await outbound_delivery.dispatch(message, idempotency_key="original-request", team_id=1,
        sender=lambda: original.send_message(settings.target(23), remote["content"], idempotency_key="original-request"))
    assert first["status"] == "unknown" and first["provider_message_id"] == ""
    with config_store.connection_scope("original-account"):
        store_event({**remote, "event": "message_updated", "account": {"id": 7}, "inbox": {"id": 11},
            "conversation": {"id": 23, "inbox_id": 11}}, settings=settings, team_id=1, delivery_id="verified-delivery-81")
    # Recreate adapters against the same durable intent/inbox, as after restart.
    await ChannelRegistry().close_all()
    fresh = ChannelRegistry().get("chatwoot", "original-account")
    await attach(fresh)
    return fresh, remote, calls, message


@pytest.mark.asyncio
async def test_lost_response_recovers_original_receipt_and_continues_polling(tool_env):
    with tenant_scope(1):
        config_store.create_connection("telegram", {"bot_token": "not-used"}, connection_id="other-account")
        adapter, remote, calls, message = await interrupted_delivery()
        with config_store.connection_scope("original-account"):
            await reconcile_pending_receipts(adapter._adapter, team_id=1)
            recovered = outbound_delivery.get_delivery("original-request", team_id=1)
            assert recovered["status"] == "accepted" and recovered["provider_state"] == "delivered"
            assert recovered["provider_message_id"] == "81" and recovered["persisted"]
            assert len(message_store.get_messages(7, connection_id="original-account")) == 1
            assert message_store.list_inbox(RECEIPT_CHANNEL) == []
            # No new webhook: the original outbox drives status readback.
            remote["status"] = "read"
            await reconcile_pending_receipts(adapter._adapter, team_id=1)
            assert outbound_delivery.get_delivery("original-request", team_id=1)["provider_state"] == "read"
            again = await outbound_delivery.dispatch(message, idempotency_key="original-request", team_id=1,
                sender=lambda: adapter.send_message(message.contact_id, message.content, idempotency_key="original-request"))
            assert again["replayed"] and again["provider_message_id"] == "81"
            assert len(message_store.get_messages(7, connection_id="original-account")) == 1
        assert sum(request.method == "POST" for request in calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("altered", [
    {"content": "different text"},
    {"content_attributes": {"kellai_request_id": "another-request"}},
    {"inbox_id": 12}, {"conversation_id": 24}, {"private": True},
])
async def test_callback_request_id_alone_cannot_recover_different_message(tool_env, altered):
    with tenant_scope(1):
        adapter, remote, calls, _ = await interrupted_delivery()
        remote.update(altered)
        with config_store.connection_scope("original-account"):
            await reconcile_pending_receipts(adapter._adapter, team_id=1)
            original = outbound_delivery.get_delivery("original-request", team_id=1)
            assert original["status"] == "unknown" and original["provider_message_id"] == ""
            assert len(message_store.list_inbox(RECEIPT_CHANNEL)) == 1
            assert message_store.get_messages(7, connection_id="original-account") == []
        assert sum(request.method == "POST" for request in calls) == 1


@pytest.mark.asyncio
async def test_same_attempt_late_ack_does_not_overwrite_authenticated_readback(tool_env):
    with tenant_scope(1):
        adapter, _, calls, _ = await interrupted_delivery()
        with sqlite3.connect(str(tool_env / "kellai.db")) as conn:
            token = conn.execute("SELECT delivery_token FROM kellai_outbound_deliveries WHERE request_id='original-request'").fetchone()[0]
        with config_store.connection_scope("original-account"):
            await reconcile_pending_receipts(adapter._adapter, team_id=1)
            for result in ({"success": False, "delivery_state": "unknown"},
                           {"success": True, "message_id": "81", "delivery_state": "accepted"}):
                receipt = outbound_delivery.complete_external(idempotency_key="original-request", delivery_token=token,
                                                               result=result, team_id=1)
                assert receipt["provider_state"] == "delivered" and receipt["provider_message_id"] == "81"
            with pytest.raises(outbound_delivery.DeliveryConflict):
                outbound_delivery.complete_external(idempotency_key="original-request", delivery_token=token,
                    result={"success": True, "message_id": "different-message"}, team_id=1)
        assert sum(request.method == "POST" for request in calls) == 1


@pytest.mark.asyncio
async def test_pending_provider_receipts_rotate_without_changing_state_time(tool_env):
    with tenant_scope(1):
        adapter, _, _, message = await interrupted_delivery()
        with config_store.connection_scope("original-account"):
            await reconcile_pending_receipts(adapter._adapter, team_id=1)
            other = message.model_copy(update={"content": "second original text"})
            await outbound_delivery.dispatch(other, idempotency_key="second-request", team_id=1,
                sender=lambda: accepted("82"))
            with sqlite3.connect(str(tool_env / "kellai.db")) as conn:
                before = dict(conn.execute("SELECT request_id,updated_at FROM kellai_outbound_deliveries"))
            first = outbound_delivery.pending_provider_receipts(team_id=1, connection_id="original-account", channel_type="chatwoot", limit=1)
            second = outbound_delivery.pending_provider_receipts(team_id=1, connection_id="original-account", channel_type="chatwoot", limit=1)
            assert first[0]["request_id"] != second[0]["request_id"]
            with sqlite3.connect(str(tool_env / "kellai.db")) as conn:
                assert dict(conn.execute("SELECT request_id,updated_at FROM kellai_outbound_deliveries")) == before


async def accepted(message_id):
    return {"success": True, "message_id": message_id, "delivery_state": "accepted"}


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked_at,expected_reads", [("conversation", 1), ("message", 2), ("commit", 2)])
async def test_revoked_account_cannot_continue_receipt_reads_or_commit(tool_env, monkeypatch, revoked_at, expected_reads):
    with tenant_scope(1):
        adapter, remote, _, _ = await interrupted_delivery()
        calls = []

        def revoke():
            config_store.update_connection("original-account", enabled=False, connected=False, status="revoked")

        def provider(request):
            calls.append(request)
            assert request.method == "GET"
            is_message = request.url.path.endswith("/messages")
            if (revoked_at == "message" and is_message) or (revoked_at == "conversation" and not is_message):
                revoke()
            return httpx.Response(200, json={"payload": [remote]} if is_message else {"id": 23, "inbox_id": 11})

        raw = adapter._adapter
        await raw._client.aclose()
        raw._client = httpx.AsyncClient(base_url="https://gateway.example", transport=httpx.MockTransport(provider))
        if revoked_at == "commit":
            original = raw.message_receipt

            async def receipt_then_revoke(*args):
                result = await original(*args)
                revoke()
                return result

            monkeypatch.setattr(raw, "message_receipt", receipt_then_revoke)
        with config_store.connection_scope("original-account"):
            await reconcile_pending_receipts(raw, team_id=1)
            assert len(calls) == expected_reads
            assert outbound_delivery.get_delivery("original-request", team_id=1)["status"] == "unknown"
            assert len(message_store.list_inbox(RECEIPT_CHANNEL)) == 1
            assert message_store.get_messages(7, connection_id="original-account") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled_by_caller", [False, True])
async def test_receipt_deadline_and_cancellation_keep_original_work_pending(tool_env, monkeypatch, cancelled_by_caller):
    from app.services import chatwoot_gateway
    with tenant_scope(1):
        adapter, _, _, _ = await interrupted_delivery()
        entered, cancelled = asyncio.Event(), []

        async def blocked(request):
            assert request.method == "GET"
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        raw = adapter._adapter
        await raw._client.aclose()
        raw._client = httpx.AsyncClient(base_url="https://gateway.example", transport=httpx.MockTransport(blocked))
        monkeypatch.setattr(chatwoot_gateway, "RECEIPT_TOTAL_TIMEOUT_SECONDS", 0.02 if not cancelled_by_caller else 5.0)
        with config_store.connection_scope("original-account"):
            task = asyncio.create_task(reconcile_pending_receipts(raw, team_id=1))
            await asyncio.wait_for(entered.wait(), timeout=1)
            if cancelled_by_caller:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await asyncio.wait_for(task, timeout=1)
            assert cancelled == [True]
            assert outbound_delivery.get_delivery("original-request", team_id=1)["status"] == "unknown"
            assert len(message_store.list_inbox(RECEIPT_CHANNEL)) == 1
