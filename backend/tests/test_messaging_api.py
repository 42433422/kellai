"""Authenticated product paths with real SQLite and an isolated provider boundary."""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.channels import ChannelRegistry, config_store
from app.services import message_store
from app.services.tenant_context import current_team_id, tenant_scope


@pytest.fixture
def product(monkeypatch, tmp_path):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KELLAI_CHANNEL_WORKER_ENABLED", "0")
    monkeypatch.delenv("KELLAI_CHANNEL_CONFIG_PATH", raising=False)
    from app import main
    from app.services import auth, crm_store
    from app.services.pipeline import create_customer, save_pipeline

    importlib.reload(crm_store)
    importlib.reload(auth)
    monkeypatch.setattr(main, "_STRICT_AUTH", False)  # boundary holds in dev, too
    accounts = [auth.register_user(email=f"{name}@example.test", password="TestSecret123!",
                                   display_name=name) for name in ("alpha", "beta")]
    assert all(account["success"] for account in accounts)
    calls = []

    class Provider:
        fail_unknown = False

        async def send_message(self, contact_id, content, **kwargs):
            calls.append((current_team_id(), contact_id, content, kwargs))
            if self.fail_unknown:
                raise TimeoutError("provider accepted request but response was lost")
            return {"success": True, "message_id": f"provider-{len(calls)}", "delivery_state": "accepted"}

        async def receive_messages(self, *, limit=50, **kwargs):
            from app.channels.wecom import WeComAdapter
            return await WeComAdapter().receive_messages(limit=limit)

    provider = Provider()
    original_get = ChannelRegistry.get
    monkeypatch.setattr(ChannelRegistry, "get", lambda registry, kind:
                        provider if kind in {"telegram", "wework", "douyin"} else original_get(registry, kind))
    customers = []
    for account in accounts:
        team_id = int(account["user"]["team_id"])
        with tenant_scope(team_id):
            doc = create_customer({"name": f"customer-{team_id}"})
            doc["channel_contacts"] = {"telegram": "stable-chat", "wework": "stable-chat", "douyin": "stable-chat"}
            save_pipeline(doc)
            customers.append(int(doc["customer_id"]))
            config_store.save("telegram", {"bot_token": f"private-{team_id}"}, enabled=True, connected=True)
            config_store.save("wework", {"corp_id": f"corp-{team_id}"}, enabled=False)
            config_store.save("douyin", {}, enabled=True)
    client = TestClient(main.create_app(), client=("127.0.0.1", 50001))
    result = SimpleNamespace(client=client, accounts=accounts, customers=customers, provider=provider,
                             calls=calls, auth=auth, main=main, tmp_path=tmp_path)
    result.headers = [{"Authorization": f"Bearer {account['access_token']}"} for account in accounts]
    result.body = {"customer_id": customers[0], "channel_type": "telegram", "contact_id": "stable-chat",
                   "content": "真实边界测试（provider isolated）", "client_request_id": "request-one"}
    yield result
    client.close()


def test_send_persists_and_replays_once_with_payload_conflict(product):
    first = product.client.post("/api/kellai/messages/send", json=product.body, headers=product.headers[0])
    assert first.status_code == 200, first.text
    receipt = first.json()["data"]
    assert receipt["status"] == "accepted" and receipt["persisted"]
    assert receipt["provider_state"] == "accepted"  # never claim delivered
    second = product.client.post("/api/kellai/messages/send", json=product.body, headers=product.headers[0])
    assert second.json()["data"]["replayed"]
    assert len(product.calls) == 1
    conflict = product.client.post("/api/kellai/messages/send", json={**product.body, "content": "different"},
                                   headers=product.headers[0])
    assert conflict.status_code == 409
    with tenant_scope(int(product.accounts[0]["user"]["team_id"])):
        assert len(message_store.get_messages(product.customers[0])) == 1


def test_timeout_can_only_query_or_replay_original_receipt(product):
    product.provider.fail_unknown = True
    first = product.client.post("/api/kellai/messages/send", json=product.body, headers=product.headers[0])
    assert first.json()["data"]["status"] == "unknown"
    assert not first.json()["success"]
    queried = product.client.get("/api/kellai/messages/requests/request-one", headers=product.headers[0])
    assert queried.json()["data"]["status"] == "unknown"
    again = product.client.post("/api/kellai/messages/send", json=product.body, headers=product.headers[0])
    assert again.json()["data"]["status"] == "unknown"
    assert len(product.calls) == 1


def test_service_bridge_uses_one_ledger_and_freezes_reply_context(product, monkeypatch):
    from app.channels.douyin import DouyinAdapter
    monkeypatch.setenv("KELLAI_DOUYIN_BRIDGE_KEY", "isolated-bridge-key")
    calls = []

    async def provider_send(self, contact_id, content, **kwargs):
        calls.append((contact_id, content, kwargs))
        return {"success": True, "message_id": "actual-platform-id", "delivery_state": "accepted"}

    monkeypatch.setattr(DouyinAdapter, "send_message", provider_send)
    body = {"team_id": int(product.accounts[0]["user"]["team_id"]), "contact_id": "cloud-customer",
            "customer_id": 987654, "content": "reply", "client_request_id": "bridge-one",
            "persona_id": "authorized-persona", "reply_context": {"conversation_id": "original-conversation"}}
    endpoint = "/api/kellai/internal/douyin/messages/send"
    assert product.client.post(endpoint, json=body).status_code == 401
    headers = {"X-Kellai-Douyin-Bridge-Key": "isolated-bridge-key"}
    first = product.client.post(endpoint, json=body, headers=headers)
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["message_id"] == "actual-platform-id"
    assert data["receipt"]["provider_message_id"] == "actual-platform-id"
    assert data["receipt"]["request_id"] == "bridge-one"
    assert data["receipt"]["persisted"] is True
    repeat = product.client.post(endpoint, json=body, headers=headers)
    assert repeat.json()["data"]["receipt"]["replayed"] is True
    assert len(calls) == 1
    assert calls[0][2]["idempotency_key"] == "bridge-one"
    assert calls[0][2]["_bridge_local_execution"] is True
    assert calls[0][2]["customer_id"] != 987654  # Desktop IDs are not cloud customer IDs.
    changed = {**body, "reply_context": {"conversation_id": "different-conversation"}}
    assert product.client.post(endpoint, json=changed, headers=headers).status_code == 409
    assert len(calls) == 1


def test_relay_manual_sync_preserves_the_desktop_consumption_cursor(product, monkeypatch):
    from app.services.channel_ingest import sync_inbox
    from app.services.douyin_channel import pull_team_inbox
    monkeypatch.setenv("KELLAI_DOUYIN_BRIDGE_KEY", "isolated-bridge-key")
    team_id = int(product.accounts[0]["user"]["team_id"])
    with tenant_scope(team_id):
        message_store.push_inbox("douyin", contact_id="remote-openid", content="incoming", direction="inbound",
                                 msg_id="relay-owned-event", metadata={"team_id": team_id})
        result = asyncio.run(sync_inbox(team_id=team_id, channel_type="douyin"))
        assert result["data"]["synced"] == 0
        assert result["data"]["relay_channels"] == ["douyin"]
        assert len(pull_team_inbox(team_id=team_id)) == 1


def test_recipient_and_tenant_are_verified_before_external_send(product):
    missing = product.client.post("/api/kellai/messages/send", json={**product.body, "contact_id": "other-person"},
                                   headers=product.headers[0])
    assert missing.status_code == 409
    absent = product.client.post("/api/kellai/messages/send", json={**product.body, "customer_id": 123456789},
                                  headers=product.headers[0])
    assert absent.status_code == 404
    assert not product.calls
    product.client.post("/api/kellai/messages/send", json=product.body, headers=product.headers[0])
    assert product.client.get("/api/kellai/messages/requests/request-one", headers=product.headers[1]).status_code == 404
    other = product.client.post("/api/kellai/messages/send", json=product.body, headers=product.headers[1])
    assert other.status_code == 200
    assert {call[0] for call in product.calls} == {int(account["user"]["team_id"]) for account in product.accounts}


def test_dev_mode_still_requires_login_and_readonly_cannot_enable_autosend(product):
    assert product.client.get("/api/kellai/channels").status_code == 401
    assert product.client.post("/api/kellai/messages/send", json=product.body).status_code == 401
    assert product.client.put("/api/kellai/ai/llm-config", json={}).status_code == 401
    with product.auth._conn() as conn:
        conn.execute("UPDATE kellai_users SET role='readonly' WHERE id=?", (product.accounts[0]["user"]["id"],))
    assert product.client.post("/api/kellai/messages/send", json=product.body, headers=product.headers[0]).status_code == 403
    assert product.client.put("/api/kellai/ai/llm-config", json={"auto_reply_enabled": True},
                              headers=product.headers[0]).status_code == 403
    assert product.client.post("/api/kellai/ai/llm-probe", headers=product.headers[0]).status_code == 403
    assert product.client.put("/api/kellai/channels/telegram/config", json={"config": {}},
                              headers=product.headers[0]).status_code == 403
    assert not product.calls


def test_public_channel_config_and_save_response_are_redacted(product):
    response = product.client.get("/api/kellai/channels", headers=product.headers[0])
    assert response.status_code == 200
    rows = response.json()["data"]
    channel = next(row for row in rows if row["type"] == "telegram")
    assert channel["config"]["bot_token"] == "********"
    assert channel["capabilities"]["send"]
    assert not channel["capabilities"]["receive"]
    updated = product.client.put("/api/kellai/channels/telegram/config", headers=product.headers[0],
                                  json={"config": {"bot_token": "new-test-secret"}})
    assert "new-test-secret" not in updated.text
    assert updated.json()["data"]["config"]["bot_token"] == "********"


def _binding(product, scopes):
    from app.services import xcmax_integration
    actor = product.accounts[0]["user"]
    with tenant_scope(int(actor["team_id"])):
        xcmax_integration._write({"connection": {
            "access_token": "local-pairing-token", "connection_id": "local-binding",
            "authorized_scopes": scopes, "team_id": int(actor["team_id"]), "authorized_by": {"id": actor["id"]},
        }})
    return {"Authorization": "Bearer local-pairing-token"}


def test_xcmax_old_read_binding_cannot_send_or_read_channel_credentials(product):
    headers = _binding(product, ["customer_profiles.read", "customer_conversations.read"])
    assert product.client.post("/api/kellai/integrations/xcmax/messages/send", json=product.body, headers=headers).status_code == 403
    assert product.client.get("/api/kellai/integrations/xcmax/channels", headers=headers).status_code == 403
    assert not product.calls


def test_xcmax_explicit_scope_uses_same_ledger_and_revocation(product):
    headers = _binding(product, ["channels.read", "messages.send"])
    channels = product.client.get("/api/kellai/integrations/xcmax/channels", headers=headers)
    assert channels.status_code == 200, channels.text
    assert isinstance(channels.json()["data"]["channels"], list)
    response = product.client.post("/api/kellai/integrations/xcmax/messages/send", json=product.body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["persisted"]
    assert product.client.get("/api/kellai/integrations/xcmax/messages/requests/request-one", headers=headers).json()["data"]["status"] == "accepted"
    assert product.client.post("/api/kellai/integrations/xcmax/messages/send",
                               json={**product.body, "desktop_result": {"success": True}}, headers=headers).status_code == 422
    with product.auth._conn() as conn:
        conn.execute("UPDATE kellai_users SET role='readonly' WHERE id=?", (product.accounts[0]["user"]["id"],))
    assert product.client.post("/api/kellai/integrations/xcmax/messages/send", json=product.body, headers=headers).status_code == 403
    assert len(product.calls) == 1


def test_xcmax_original_message_readback_survives_recent_history_window(product):
    response = product.client.post("/api/kellai/messages/send", json=product.body, headers=product.headers[0])
    assert response.status_code == 200, response.text
    message_id = response.json()["data"]["message_id"]
    headers = _binding(product, ["customer_conversations.read"])
    team_id = int(product.accounts[0]["user"]["team_id"])
    newer = datetime.now(timezone.utc)
    # Seed a busy real message table without dispatching 101 more external sends.
    with tenant_scope(team_id), message_store._connect() as conn:
        conn.executemany(
            "INSERT INTO kellai_messages "
            "(team_id, id, customer_id, channel_type, contact_id, direction, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(team_id, f"newer-{i}", product.customers[0], "telegram", "stable-chat", "inbound",
              f"new message {i}", (newer + timedelta(seconds=i + 1)).isoformat()) for i in range(101)],
        )
    path = f"/api/kellai/integrations/xcmax/customers/{product.customers[0]}/conversations"
    recent = product.client.get(path, params={"limit": 1000}, headers=headers).json()["data"]["messages"]
    assert len(recent) == 100 and all(row["id"] != message_id for row in recent)
    original = product.client.get(path, params={"message_id": message_id, "limit": 1}, headers=headers)
    assert original.status_code == 200, original.text
    rows = original.json()["data"]["messages"]
    assert len(rows) == 1 and rows[0]["id"] == message_id
    assert rows[0]["content"] == product.body["content"]
    assert rows[0]["metadata"]["delivery_request_id"] == product.body["client_request_id"]
    assert len(product.calls) == 1


@pytest.mark.parametrize("other_scope", ["tenant", "customer"])
def test_xcmax_message_identity_cannot_replace_tenant_or_customer_scope(product, other_scope):
    from app.channels.base import UnifiedMessage
    from app.services.pipeline import create_customer, save_pipeline

    headers = _binding(product, ["customer_conversations.read"])
    account = product.accounts[1 if other_scope == "tenant" else 0]
    team_id = int(account["user"]["team_id"])
    with tenant_scope(team_id):
        customer_id = product.customers[1]
        if other_scope == "tenant":
            assert customer_id == product.customers[0]
        else:
            customer = create_customer({"name": "other customer"})
            save_pipeline(customer)
            customer_id = int(customer["customer_id"])
            assert customer_id != product.customers[0]
        message_store.save_message(UnifiedMessage(
            id="scoped-original", customer_id=customer_id, channel_type="telegram",
            contact_id="private-recipient", contact_name="other scope", direction="outbound",
            content="private other scope",
            metadata={"team_id": team_id}, created_at=datetime.now(timezone.utc).isoformat(),
        ))
    path = f"/api/kellai/integrations/xcmax/customers/{product.customers[0]}/conversations"
    for message_id in ("scoped-original", "' OR 1=1 --"):
        response = product.client.get(path, params={"message_id": message_id}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["messages"] == []
    assert not product.calls


def test_xcmax_exact_message_read_requires_original_scope_and_active_binding(product):
    path = f"/api/kellai/integrations/xcmax/customers/{product.customers[0]}/conversations"
    query = {"message_id": "scoped-original"}
    headers = _binding(product, ["customer_profiles.read"])
    assert product.client.get(path, params=query, headers=headers).status_code == 403
    headers = _binding(product, ["customer_conversations.read"])
    assert product.client.get(path, params=query, headers=headers).status_code == 200
    from app.services import xcmax_integration

    with tenant_scope(int(product.accounts[0]["user"]["team_id"])):
        xcmax_integration._write({"connection": None})
    assert product.client.get(path, params=query, headers=headers).status_code == 401
    assert not product.calls


def test_pairing_token_is_not_a_remote_api_key(product):
    headers = _binding(product, ["channels.read", "messages.send"])
    remote = TestClient(product.main.create_app(), client=("198.51.100.22", 50001))
    assert remote.get("/api/kellai/integrations/xcmax/channels", headers=headers).status_code == 403
    remote.close()


def test_native_execution_requires_durable_single_use_reservation(product):
    headers = {**product.headers[0], "X-Kellai-Desktop-Delivery": "1"}
    body = {**product.body, "channel_type": "douyin"}
    prepared = product.client.post("/api/kellai/messages/prepare", json=body, headers=headers)
    assert prepared.status_code == 200, prepared.text
    reservation = prepared.json()["data"]
    assert reservation["dispatch_allowed"] and reservation["delivery_token"]
    repeated = product.client.post("/api/kellai/messages/prepare", json=body, headers=headers).json()["data"]
    assert not repeated["dispatch_allowed"] and "delivery_token" not in repeated
    result = {"success": True, "source": "douyin_desktop_automation", "message_sent": True, "contact_id": "stable-chat"}
    forged = product.client.post("/api/kellai/messages/send", json={**body, "desktop_result": result}, headers=headers)
    assert forged.status_code == 409
    # Recording an already executed native result remains valid after disabling
    # the channel; no new external execution is permitted.
    with tenant_scope(int(product.accounts[0]["user"]["team_id"])):
        config_store.save("douyin", {}, enabled=False)
    completed = product.client.post("/api/kellai/messages/send",
        json={**body, "desktop_result": result, "delivery_token": reservation["delivery_token"]}, headers=headers)
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["status"] == "accepted"
    assert completed.json()["data"]["persisted"]
    assert not product.calls


def test_enqueue_failure_does_not_acknowledge_inbox(product, monkeypatch):
    from app.services import auto_reply_runtime, channel_ingest
    team_id = int(product.accounts[0]["user"]["team_id"])
    with tenant_scope(team_id):
        message_store.push_inbox("wework", contact_id="stable-chat", contact_name="Customer", direction="inbound",
                                 content="你好", msg_id="inbox-enqueue-failure", metadata={"team_id": team_id})
        enqueue = auto_reply_runtime.enqueue_message
        monkeypatch.setattr(auto_reply_runtime, "enqueue_message", lambda _: (_ for _ in ()).throw(RuntimeError("disk busy")))
        first = asyncio.run(channel_ingest.sync_inbox(team_id=team_id, channel_type="wework"))
        assert not first["success"]
        assert len(message_store.list_inbox("wework")) == 1
        monkeypatch.setattr(auto_reply_runtime, "enqueue_message", enqueue)
        second = asyncio.run(channel_ingest.sync_inbox(team_id=team_id, channel_type="wework"))
        assert second["success"]
        assert not message_store.list_inbox("wework")


def test_api_worker_completes_existing_inbox_model_and_ledger_once(product, monkeypatch):
    from app.services import ai_copilot, auto_reply_runtime, channel_worker
    monkeypatch.setattr(auto_reply_runtime, "_enabled_config", lambda: {
        "autoReplyEnabled": True, "autoReplyStages": [], "confirmScenarios": []})
    monkeypatch.setattr(ai_copilot, "generate_auto_reply", lambda *args, **kwargs: {
        "draft": "您好，请问需要了解哪项服务？", "can_auto_send": True, "generation_source": "llm"})
    team_id = int(product.accounts[0]["user"]["team_id"])
    with tenant_scope(team_id):
        config_store.save("wework", {}, enabled=True, connected=True)
        message_store.push_inbox("wework", contact_id="stable-chat", contact_name="Customer", direction="inbound",
                                 content="你好", msg_id="worker-inbound", metadata={"team_id": team_id})
    summary = asyncio.run(channel_worker.run_once())
    assert summary["jobs"] == 0 and summary["errors"] == 0  # Three-second inbound debounce.
    later = datetime.now(timezone.utc) + timedelta(seconds=4)
    monkeypatch.setattr(auto_reply_runtime, "_now", lambda: later)
    summary = asyncio.run(channel_worker.run_once())
    assert summary["jobs"] == 1 and summary["errors"] == 0
    assert len(product.calls) == 1
    again = asyncio.run(channel_worker.run_once())
    assert again["jobs"] == 0 and len(product.calls) == 1
    with tenant_scope(team_id):
        rows = message_store.get_messages(product.customers[0])
        assert {row.direction for row in rows} == {"inbound", "outbound"}
        assert auto_reply_runtime.runtime_status(team_id=team_id)["counts"].get("sent") == 1
