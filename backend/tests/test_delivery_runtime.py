from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.channels.base import UnifiedMessage
from app.services import message_store, outbound_delivery
from app.services.tenant_context import tenant_scope


@pytest.fixture
def delivery_db(monkeypatch, tmp_path):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    db = tmp_path / "kellai.db"
    monkeypatch.setattr(outbound_delivery, "_crm_db_path", lambda: db)
    monkeypatch.setattr(message_store, "_crm_db_path", lambda: db)
    from app.services import growth_loop, workforce_routing

    monkeypatch.setattr(growth_loop, "apply_message_to_growth_loop", lambda _msg: {})
    monkeypatch.setattr(workforce_routing, "touch_assignment", lambda *_a, **_kw: None)
    return db


def message(*, team=3, contact="contact-7", content="您好"):
    return UnifiedMessage(
        id="transient-client-id", customer_id=7, channel_type="telegram",
        contact_id=contact, contact_name="客户", direction="outbound", content=content,
        metadata={"team_id": team}, created_at=datetime.now(timezone.utc).isoformat(),
    )


def test_parallel_sqlite_reservations_grant_one_sender(delivery_db):
    def reserve(_index):
        return outbound_delivery.prepare_external(message(), idempotency_key="threaded", team_id=3)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(reserve, range(16)))
    assert sum(row["dispatch_allowed"] for row in receipts) == 1
    assert sum("delivery_token" in row for row in receipts) == 1
    assert len({row["message_id"] for row in receipts}) == 1


@pytest.mark.asyncio
async def test_replay_is_one_provider_post_and_one_durable_message(delivery_db):
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"message_id": "provider-1"})

    async def send():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            response = await client.post("https://provider.invalid/send", json={"text": "您好"})
        return {"success": True, "message_id": response.json()["message_id"]}

    first = await outbound_delivery.dispatch(message(), idempotency_key="request-1", sender=send, team_id=3)
    again = await outbound_delivery.dispatch(message(), idempotency_key="request-1", sender=send, team_id=3)
    assert first["status"] == "accepted" and first["persisted"]
    assert again["replayed"] and again["message_id"] == first["message_id"]
    assert calls == [{"text": "您好"}]
    with sqlite3.connect(str(delivery_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM kellai_messages").fetchone()[0] == 1
    rows = message_store.get_messages(7, team_id=3)
    assert rows[0].metadata["provider_message_id"] == "provider-1"


@pytest.mark.asyncio
async def test_same_key_cannot_change_content_or_recipient(delivery_db):
    async def send():
        return {"success": True, "message_id": "remote-1"}

    await outbound_delivery.dispatch(message(), idempotency_key="request", sender=send, team_id=3)
    for changed in (message(content="不同内容"), message(contact="other-person")):
        with pytest.raises(outbound_delivery.DeliveryConflict):
            await outbound_delivery.dispatch(changed, idempotency_key="request", sender=send, team_id=3)


@pytest.mark.asyncio
async def test_concurrent_same_request_has_one_sender(delivery_db):
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def send():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"success": True, "message_id": "remote-1"}

    pending = asyncio.create_task(outbound_delivery.dispatch(message(), idempotency_key="parallel", sender=send, team_id=3))
    await started.wait()
    second = await outbound_delivery.dispatch(message(), idempotency_key="parallel", sender=send, team_id=3)
    assert second["status"] == "sending" and not second["dispatch_allowed"]
    release.set()
    assert (await pending)["persisted"]
    assert calls == 1


@pytest.mark.asyncio
async def test_provider_timeout_is_unknown_and_never_retried(delivery_db):
    calls = 0

    async def send():
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("provider may have accepted")

    first = await outbound_delivery.dispatch(message(), idempotency_key="timeout", sender=send, team_id=3)
    again = await outbound_delivery.dispatch(message(), idempotency_key="timeout", sender=send, team_id=3)
    assert first["status"] == again["status"] == "unknown"
    assert not first["success"] and not again["dispatch_allowed"]
    assert calls == 1


def test_desktop_reservation_is_single_use_and_receipt_is_fenced(delivery_db):
    first = outbound_delivery.prepare_external(message(), idempotency_key="native", team_id=3)
    again = outbound_delivery.prepare_external(message(), idempotency_key="native", team_id=3)
    assert first["dispatch_allowed"]
    assert not again["dispatch_allowed"] and "delivery_token" not in again
    result = {"success": True, "message_id": "native-1"}
    with pytest.raises(outbound_delivery.DeliveryLeaseError):
        outbound_delivery.complete_external(idempotency_key="native", delivery_token="wrong", result=result, team_id=3)
    with pytest.raises(outbound_delivery.DeliveryLeaseError):
        outbound_delivery.complete_external(idempotency_key="native", delivery_token=first["delivery_token"], result=result, team_id=4)
    saved = outbound_delivery.complete_external(idempotency_key="native", delivery_token=first["delivery_token"], result=result, team_id=3)
    replayed = outbound_delivery.complete_external(idempotency_key="native", delivery_token=first["delivery_token"], result=result, team_id=3)
    assert saved["persisted"] and replayed["replayed"]
    with pytest.raises(outbound_delivery.DeliveryConflict):
        outbound_delivery.complete_external(idempotency_key="native", delivery_token=first["delivery_token"], result={"success": False}, team_id=3)


def test_abandoned_external_attempt_expires_to_unknown_not_resend(delivery_db):
    first = outbound_delivery.prepare_external(message(), idempotency_key="crash", team_id=3)
    with sqlite3.connect(str(delivery_db)) as conn:
        conn.execute("UPDATE kellai_outbound_deliveries SET lease_until=?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))
    again = outbound_delivery.prepare_external(message(), idempotency_key="crash", team_id=3)
    assert again["status"] == "unknown" and not again["dispatch_allowed"]
    # A late result from the very same original attempt can reconcile it.
    reconciled = outbound_delivery.complete_external(idempotency_key="crash", delivery_token=first["delivery_token"], result={"success": True, "message_id": "late-1"}, team_id=3)
    assert reconciled["success"] and reconciled["persisted"]


@pytest.mark.asyncio
async def test_provider_receipt_survives_projection_failure(monkeypatch, delivery_db):
    calls = 0
    save = message_store.save_message

    async def send():
        nonlocal calls
        calls += 1
        return {"success": True, "message_id": "remote-1"}

    def fail(_msg):
        raise sqlite3.OperationalError("disk temporarily unavailable")

    monkeypatch.setattr(message_store, "save_message", fail)
    first = await outbound_delivery.dispatch(message(), idempotency_key="projection", sender=send, team_id=3)
    assert first["success"] and not first["persisted"]
    monkeypatch.setattr(message_store, "save_message", save)
    restored = outbound_delivery.get_delivery("projection", team_id=3)
    assert restored["persisted"] and restored["message_id"] == first["message_id"]
    assert calls == 1


@pytest.mark.asyncio
async def test_recovery_after_message_commit_does_not_repeat_crm_projection(monkeypatch, delivery_db):
    async def send():
        return {"success": True, "message_id": "remote-1"}

    first = await outbound_delivery.dispatch(message(), idempotency_key="projection", sender=send, team_id=3)
    with sqlite3.connect(str(delivery_db)) as conn:
        conn.execute("UPDATE kellai_outbound_deliveries SET projected=0")

    def unexpected(_msg):
        pytest.fail("existing message was projected to CRM again")

    monkeypatch.setattr(message_store, "save_message", unexpected)
    restored = await outbound_delivery.dispatch(message(), idempotency_key="projection", sender=send, team_id=3)
    assert restored["persisted"] and first["message_id"] == restored["message_id"]


@pytest.mark.asyncio
async def test_provider_receipts_are_tenant_scoped_and_monotonic(delivery_db):
    async def send():
        return {"success": True, "message_id": "provider-1", "delivery_state": "accepted"}

    await outbound_delivery.dispatch(message(), idempotency_key="receipts", sender=send, team_id=3)
    assert not outbound_delivery.reconcile_receipt(team_id=4, channel_type="telegram", provider_message_id="provider-1", state="delivered")
    assert not outbound_delivery.reconcile_receipt(team_id=3, channel_type="other", provider_message_id="provider-1", state="delivered")
    assert outbound_delivery.reconcile_receipt(team_id=3, channel_type="telegram", provider_message_id="provider-1", state="delivered")
    assert not outbound_delivery.reconcile_receipt(team_id=3, channel_type="telegram", provider_message_id="provider-1", state="sent")
    assert not outbound_delivery.reconcile_receipt(team_id=3, channel_type="telegram", provider_message_id="provider-1", state="failed")
    assert outbound_delivery.reconcile_receipt(team_id=3, channel_type="telegram", provider_message_id="provider-1", state="read")
    assert message_store.get_messages(7, team_id=3)[0].metadata["delivery_state"] == "read"


def test_authenticated_context_rejects_explicit_other_tenant(delivery_db):
    with tenant_scope(3):
        with pytest.raises(PermissionError):
            outbound_delivery.prepare_external(message(team=4), idempotency_key="tenant", team_id=4)
        with pytest.raises(PermissionError):
            outbound_delivery.get_delivery("tenant", team_id=4)


@pytest.mark.asyncio
async def test_same_request_key_in_two_tenants_is_independent(delivery_db):
    async def send():
        return {"success": True, "message_id": "remote-same"}

    first = await outbound_delivery.dispatch(message(team=3), idempotency_key="shared", sender=send, team_id=3)
    second = await outbound_delivery.dispatch(message(team=4), idempotency_key="shared", sender=send, team_id=4)
    assert first["message_id"] != second["message_id"]
    assert len(message_store.get_messages(7, team_id=3)) == len(message_store.get_messages(7, team_id=4)) == 1


@pytest.mark.asyncio
async def test_explicit_provider_rejection_is_terminal_for_that_key(delivery_db):
    calls = 0

    async def send():
        nonlocal calls
        calls += 1
        return {"success": False, "error": "recipient_not_found", "definitely_not_sent": True}

    first = await outbound_delivery.dispatch(message(), idempotency_key="rejected", sender=send, team_id=3)
    again = await outbound_delivery.dispatch(message(), idempotency_key="rejected", sender=send, team_id=3)
    assert first["status"] == again["status"] == "failed" and calls == 1


@pytest.mark.asyncio
async def test_provider_receipt_is_bound_to_original_gateway_configuration(delivery_db):
    for gateway, key in (("old-instance", "old"), ("new-instance", "new")):
        async def send():
            return {"success": True, "message_id": "1", "gateway_id": gateway,
                    "account_id": 1, "inbox_id": 2, "conversation_id": 3}
        await outbound_delivery.dispatch(message().model_copy(update={"channel_type": "chatwoot"}),
                                         idempotency_key=key, team_id=3, sender=send)
    args = {"team_id": 3, "channel_type": "chatwoot", "provider_message_id": "1", "state": "delivered"}
    assert not outbound_delivery.reconcile_receipt(**args)
    assert not outbound_delivery.reconcile_receipt(**args, provider_context={"gateway_id": "unbound"})
    assert outbound_delivery.reconcile_receipt(**args, provider_context={
        "gateway_id": "new-instance", "account_id": 1, "inbox_id": 2, "conversation_id": 3,
    })
    assert outbound_delivery.get_delivery("old", team_id=3)["provider_state"] == "accepted"
    assert outbound_delivery.get_delivery("new", team_id=3)["provider_state"] == "delivered"
