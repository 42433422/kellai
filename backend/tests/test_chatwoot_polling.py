"""Authenticated desktop polling: durable pages, account isolation and no send replay."""
import json

import httpx
import pytest

from app.channels import ChannelRegistry, config_store
from app.services import chatwoot_gateway, message_store
from app.services.channel_ingest import sync_inbox
from app.services.tenant_context import tenant_scope


CONFIG = {"base_url": "https://chatwoot.example", "account_id": "7", "inbox_id": "11",
          "api_access_token": "first-token"}


def remote_message(mid, *, conversation=23, content=None, **extra):
    return {"id": mid, "inbox_id": 11, "conversation_id": conversation,
            "message_type": 0, "private": False, "content": content or f"message-{mid}",
            "sender": {"id": 42, "name": "Contact"}, "created_at": 1760000000 + mid, **extra}


async def bind_provider(connection_id, provider, config=None):
    item = config_store.create_connection("chatwoot", config or CONFIG, connection_id=connection_id)
    return item, await use_provider(connection_id, provider)


async def use_provider(connection_id, provider):
    adapter = ChannelRegistry().get("chatwoot", connection_id)
    with config_store.connection_scope(connection_id):
        previous = await adapter._adapter._get_client()
        client = httpx.AsyncClient(base_url=previous.base_url, headers=previous.headers,
                                   transport=httpx.MockTransport(provider))
        await previous.aclose()
        adapter._adapter._client = client
    return adapter


def provider_for(messages, calls):
    def provider(request):
        calls.append(request)
        assert request.method == "GET", "Polling cannot issue external mutations"
        if request.url.path.endswith("/conversations"):
            assert request.url.params["status"] == "all"
            assert request.url.params["inbox_id"] == "11"
            assert request.url.params["sort_by"] == "created_at_asc"
            page = int(request.url.params["page"])
            # Deliberately use one conversation per server page; no hardcoded 25.
            ids = sorted(messages)
            rows = [{"id": ids[page - 1], "inbox_id": 11}] if page <= len(ids) else []
            return httpx.Response(200, json={"data": {"payload": rows}})
        conversation = int(request.url.path.split("/")[-2])
        after = int(request.url.params["after"])
        if "before" in request.url.params:
            before = int(request.url.params["before"])
            rows = [m for m in messages[conversation] if after <= m["id"] < before][:1000]
        else:
            rows = [m for m in messages[conversation] if m["id"] > after][:100]
        return httpx.Response(200, json={"payload": rows})
    return provider


@pytest.mark.asyncio
async def test_multi_page_messages_resume_after_restart_without_a_public_webhook(tool_env):
    calls = []
    messages = {23: [remote_message(i) for i in range(1, 121)],
                24: [remote_message(121, conversation=24)]}
    provider = provider_for(messages, calls)
    with tenant_scope(1):
        await bind_provider("desktop", provider)
        for _ in range(12):
            await sync_inbox(connection_id="desktop")
        contacts = message_store.list_contacts(connection_id="desktop")
        assert len(contacts) == 2
        rows = [m for c in contacts for m in message_store.get_messages(c["customer_id"], connection_id="desktop", limit=500)]
        assert len(rows) == 121
        assert {int(m.metadata["provider_message_id"]) for m in rows} == set(range(1, 122))
        assert all(m.created_at.startswith("2025-") for m in rows)
        assert all(r.headers["authorization"] == "Bearer first-token" for r in calls)
        await ChannelRegistry().close_all()
        await use_provider("desktop", provider)
        for _ in range(6):
            await sync_inbox(connection_id="desktop")
        assert sum(len(message_store.get_messages(c["customer_id"], connection_id="desktop", limit=500)) for c in contacts) == 121
        assert any(r.url.params.get("after") == "100" for r in calls)
        assert any(r.url.params.get("after") == "120" for r in calls)


@pytest.mark.asyncio
async def test_same_remote_ids_do_not_share_progress_or_messages_between_connections(tool_env):
    calls = []
    with tenant_scope(1):
        for cid in ("first", "second"):
            provider = provider_for({23: [remote_message(81, content=cid)]}, calls)
            await bind_provider(cid, provider, {**CONFIG, "api_access_token": cid + "-token"})
            await sync_inbox(connection_id=cid)
        contacts = message_store.list_contacts()
        assert len(contacts) == 2
        for contact in contacts:
            rows = message_store.get_messages(contact["customer_id"], connection_id=contact["connection_id"])
            assert len(rows) == 1 and rows[0].content == contact["connection_id"]
        assert {r.headers["authorization"] for r in calls} == {"Bearer first-token", "Bearer second-token"}


@pytest.mark.asyncio
async def test_storage_failure_replays_page_and_never_checkpoints_unstored_message(tool_env, monkeypatch):
    calls = []
    original = chatwoot_gateway.store_event
    def fail_second(payload, **kwargs):
        if payload["id"] == 2:
            raise OSError("isolated disk failure")
        return original(payload, **kwargs)
    with tenant_scope(1):
        _, adapter = await bind_provider("desktop", provider_for({23: [remote_message(1), remote_message(2)]}, calls))
        monkeypatch.setattr(chatwoot_gateway, "store_event", fail_second)
        with pytest.raises(OSError, match="isolated disk failure"):
            await sync_inbox(connection_id="desktop")
        with config_store.connection_scope("desktop"):
            assert message_store.get_sync_progress("chatwoot", adapter._adapter.settings().target(23)) == ({}, 0)
        monkeypatch.setattr(chatwoot_gateway, "store_event", original)
        # First drain the durable first message, then safely replay the remote page.
        await sync_inbox(connection_id="desktop")
        await sync_inbox(connection_id="desktop")
        contact = message_store.list_contacts()[0]
        assert len(message_store.get_messages(contact["customer_id"], connection_id="desktop")) == 2
        assert [r.url.params["after"] for r in calls if r.url.path.endswith("/messages")] == ["0", "0"]


@pytest.mark.asyncio
async def test_config_change_during_remote_read_cannot_persist_or_advance_old_account(tool_env):
    calls = []
    normal = provider_for({23: [remote_message(1)]}, calls)
    def revoke_inflight(request):
        if request.url.path.endswith("/messages"):
            config_store.update_connection("desktop", enabled=False, expected_version=1)
        return normal(request)
    with tenant_scope(1):
        await bind_provider("desktop", revoke_inflight)
        with pytest.raises(config_store.ConnectionUnavailable):
            await sync_inbox(connection_id="desktop")
        assert message_store.list_inbox(connection_id="desktop", include_consumed=True) == []
        assert message_store.list_contacts() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"inbox_id": 99}, {"conversation_id": 99}, {"private": None}, {"id": True}, {"id": 0},
    {"message_type": None}, {"message_type": True}, {"message_type": 99}, {"content": {"not": "text"}}
])
async def test_malformed_or_wrong_account_page_does_not_advance_cursor(tool_env, invalid):
    calls = []
    normal = provider_for({23: [remote_message(1)]}, calls)
    def provider(request):
        response = normal(request)
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"payload": [remote_message(1, **invalid)]})
        return response
    with tenant_scope(1):
        _, adapter = await bind_provider("desktop", provider)
        with pytest.raises(ValueError):
            await sync_inbox(connection_id="desktop")
        with config_store.connection_scope("desktop"):
            assert message_store.get_sync_progress("chatwoot", adapter._adapter.settings().target(23)) == ({}, 0)
        assert message_store.list_inbox(connection_id="desktop", include_consumed=True) == []


@pytest.mark.asyncio
async def test_sync_progress_cas_and_receipt_fairness_preserve_received_time(tool_env):
    with tenant_scope(1):
        config_store.create_connection("chatwoot", CONFIG, connection_id="first")
        config_store.create_connection("chatwoot", CONFIG, connection_id="second")
    with tenant_scope(1), config_store.connection_scope("first"):
        assert message_store.save_sync_progress("chatwoot", "stream", {"after": 100}, revision=0)
        assert not message_store.save_sync_progress("chatwoot", "stream", {"after": 1000}, revision=0)
        assert message_store.get_sync_progress("chatwoot", "stream") == ({"after": 100}, 1)
        for i in range(3):
            message_store.push_inbox("chatwoot_receipt", contact_id="known", direction="outbound", content="", msg_id=str(i))
        before = {r["id"]: r["received_at"] for r in message_store.list_inbox("chatwoot_receipt")}
        first = message_store.list_inbox("chatwoot_receipt", limit=2, rotate=True)
        second = message_store.list_inbox("chatwoot_receipt", limit=2, rotate=True)
        assert second[0]["id"] not in {r["id"] for r in first}
        assert before == {r["id"]: r["received_at"] for r in message_store.list_inbox("chatwoot_receipt")}
    with tenant_scope(1), config_store.connection_scope("second"):
        assert message_store.get_sync_progress("chatwoot", "stream") == ({}, 0)


@pytest.mark.asyncio
async def test_backdated_large_id_cannot_skip_unseen_smaller_message_ids(tool_env):
    calls = []
    # Exact upstream ordering: old created_at first, even when its ID is larger.
    records = [remote_message(5000, created_at=1700000000)] + [remote_message(i) for i in range(1, 121)]
    with tenant_scope(1):
        _, adapter = await bind_provider("desktop", provider_for({23: records}, calls))
        for _ in range(4):
            await sync_inbox(connection_id="desktop", limit=500)
        contact = message_store.list_contacts()[0]
        rows = message_store.get_messages(contact["customer_id"], connection_id="desktop", limit=500)
        assert {int(m.metadata["provider_message_id"]) for m in rows} == {5000, *range(1, 121)}
        with config_store.connection_scope("desktop"):
            progress, _ = message_store.get_sync_progress("chatwoot", adapter._adapter.settings().target(23))
            assert progress["after"] == 5000
        assert any(dict(r.url.params) == {"after": "1", "before": "5001"} for r in calls)


@pytest.mark.asyncio
async def test_dense_backdated_interval_resumes_bisection_without_skipping_records(tool_env):
    calls = []
    records = [remote_message(4096, created_at=1700000000)] + [remote_message(i) for i in range(1, 1101)]
    with tenant_scope(1):
        _, adapter = await bind_provider("desktop", provider_for({23: records}, calls))
        await sync_inbox(connection_id="desktop", limit=500)
        with config_store.connection_scope("desktop"):
            stream = adapter._adapter.settings().target(23)
            progress, _ = message_store.get_sync_progress("chatwoot", stream)
            assert progress == {"after": 0, "upper": 2048}
        await ChannelRegistry().close_all()
        await use_provider("desktop", provider_for({23: records}, calls))
        for _ in range(24):
            await sync_inbox(connection_id="desktop", limit=500)
        # The public history API is bounded to 500; inspect durable IDs directly.
        with message_store._connect() as connection:
            ids = {int(json.loads(row[0])["provider_message_id"])
                   for row in connection.execute("SELECT metadata_json FROM kellai_messages WHERE connection_id='desktop'")}
        assert ids == {4096, *range(1, 1101)}
        with config_store.connection_scope("desktop"):
            assert message_store.get_sync_progress("chatwoot", stream)[0]["after"] == 4096
        assert all(r.method == "GET" for r in calls)


@pytest.mark.asyncio
async def test_lost_send_response_recovers_by_api_pull_without_any_webhook_or_second_post(tool_env):
    from app.channels.base import UnifiedMessage
    from app.services import outbound_delivery

    calls = []
    remote = remote_message(81, message_type=1, content="Approved original", status="delivered",
                            content_attributes={"kellai_request_id": "original-request"})
    def provider(request):
        calls.append(request)
        if request.method == "POST":
            assert json.loads(request.content)["content_attributes"]["kellai_request_id"] == "original-request"
            raise httpx.ReadTimeout("response lost after commit", request=request)
        if request.url.path.endswith("/conversations"):
            rows = [{"id": 23, "inbox_id": 11}] if request.url.params["page"] == "1" else []
            return httpx.Response(200, json={"data": {"payload": rows}})
        if request.url.path.endswith("/messages"):
            after = int(request.url.params["after"])
            rows = [dict(remote)] if after < 81 or "before" in request.url.params else []
            return httpx.Response(200, json={"payload": rows})
        return httpx.Response(200, json={"id": 23, "inbox_id": 11, "can_reply": True})
    with tenant_scope(1):
        _, adapter = await bind_provider("desktop", provider)
        target = adapter._adapter.settings().target(23)
        original = UnifiedMessage(id="", customer_id=7, connection_id="desktop", channel_type="chatwoot",
            contact_id=target, contact_name="Known recipient", direction="outbound", content=remote["content"],
            metadata={"team_id": 1}, created_at="2026-11-23T00:00:00+00:00")
        async def send():
            return await adapter.send_message(target, remote["content"], idempotency_key="original-request")
        first = await outbound_delivery.dispatch(original, idempotency_key="original-request", team_id=1, sender=send)
        assert first["status"] == "unknown" and not first["provider_message_id"]
        assert message_store.list_inbox(connection_id="desktop", include_consumed=True) == []
        await sync_inbox(connection_id="desktop")
        recovered = outbound_delivery.get_delivery("original-request", team_id=1)
        assert recovered["provider_state"] == "delivered" and recovered["provider_message_id"] == "81"
        again = await outbound_delivery.dispatch(original, idempotency_key="original-request", team_id=1, sender=send)
        assert again["replayed"] and again["provider_message_id"] == "81"
        remote["status"] = "read"
        await sync_inbox(connection_id="desktop")
        assert outbound_delivery.get_delivery("original-request", team_id=1)["provider_state"] == "read"
        assert len(message_store.get_messages(7, connection_id="desktop")) == 1
        assert sum(request.method == "POST" for request in calls) == 1


@pytest.mark.asyncio
async def test_page_commit_and_concurrent_revocation_are_serialized(tool_env, monkeypatch):
    import contextvars
    import threading

    original = chatwoot_gateway.store_event
    attempted, revoked = threading.Event(), threading.Event()
    threads, errors = [], []

    def revoke():
        attempted.set()
        try:
            config_store.update_connection("desktop", enabled=False, expected_version=1)
            revoked.set()
        except Exception as error:
            errors.append(error)

    def concurrent_revoke(payload, **kwargs):
        result = original(payload, **kwargs)
        if payload["id"] == 1:
            context = contextvars.copy_context()
            thread = threading.Thread(target=context.run, args=(revoke,))
            threads.append(thread)
            thread.start()
            assert attempted.wait(1)
            assert not revoked.is_set(), "Revocation cannot commit inside an authorized page commit"
        return result

    with tenant_scope(1):
        _, adapter = await bind_provider("desktop", provider_for({23: [remote_message(1), remote_message(2)]}, []))
        monkeypatch.setattr(chatwoot_gateway, "store_event", concurrent_revoke)
        with config_store.connection_scope("desktop"):
            await adapter._adapter._pull_inbox()
        for thread in threads:
            thread.join(timeout=3)
            assert not thread.is_alive()
        assert not errors and revoked.is_set()
        assert config_store.get_connection("desktop")["enabled"] is False
        with config_store.connection_scope("desktop"):
            assert message_store.get_sync_progress("chatwoot", adapter._adapter.settings().target(23))[0] == {"after": 2}
            assert len(message_store.list_inbox("chatwoot")) == 2
        # This batch linearized before revocation. Any later remote pull is refused.
        with pytest.raises(config_store.ConnectionUnavailable):
            await adapter.receive_messages()
