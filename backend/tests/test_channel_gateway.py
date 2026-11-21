"""Protocol-level HTTPX and real SQLite tests; no external accounts are contacted."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import time

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

os.environ.setdefault("KELLAI_APP_ENV", "development")
os.environ.setdefault("KELLAI_JWT_SECRET", "test-channel-gateway-only")
os.environ.setdefault("KELLAI_PASSWORD_SALT", "test-channel-gateway-only")

from app.channels import ChannelRegistry, config_store
from app.channels.chatwoot import ChatwootAdapter
from app.channels.http_client import BaseChannelClient, ChannelHTTPError
from app.services.tenant_context import tenant_scope

TEAM = 41
CONFIG = {"base_url": "https://gateway.example", "account_id": "7", "inbox_id": "11",
          "api_access_token": "api-secret-test", "webhook_secret": "hook-secret-test"}
GATEWAY_ID = hashlib.sha256(CONFIG["base_url"].encode()).hexdigest()[:16]
TARGET = f"chatwoot:{GATEWAY_ID}:7:11:23"


@pytest_asyncio.fixture(autouse=True)
async def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KELLAI_CHANNEL_CONFIG_PATH", str(tmp_path / "channels.json"))
    for key in list(os.environ):
        if key == "KELLAI_CHANNEL_ENV_TEAM_ID" or key.startswith(("KELLAI_CHATWOOT_", "KELLAI_TELEGRAM_", "KELLAI_WECOM_", "KELLAI_WEWORK_")):
            monkeypatch.delenv(key)
    await ChannelRegistry().close_all()
    yield
    await ChannelRegistry().close_all()


def configured():
    config_store.save("chatwoot", CONFIG, enabled=True)
    return ChannelRegistry().get("chatwoot")


def message_payload(**changes):
    payload = {"event": "message_created", "id": 81, "content": "你好，我想了解产品", "private": False,
               "account": {"id": 7}, "inbox": {"id": 11}, "conversation": {"id": 23, "inbox_id": 11},
               "message_type": "incoming", "sender": {"id": 53, "name": "测试客户"},
               "content_attributes": {}, "created_at": datetime.now(timezone.utc).isoformat()}
    payload.update(changes)
    return payload


def signed(payload, *, secret=CONFIG["webhook_secret"], timestamp=None, delivery="event-1"):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + raw,
                                    hashlib.sha256).hexdigest()
    return raw, {"Content-Type": "application/json", "X-Chatwoot-Signature": signature,
                 "X-Chatwoot-Timestamp": timestamp, "X-Chatwoot-Delivery": delivery}


def api_handler(request):
    if request.url.path.endswith("/messages") and request.method == "POST":
        return httpx.Response(200, json={"id": 91, "inbox_id": 11, "conversation_id": 23, "status": "sent"})
    if request.url.path.endswith("/messages"):
        return httpx.Response(200, json={"payload": [{"id": 91, "inbox_id": 11, "conversation_id": 23,
                                                    "message_type": 1, "private": False, "status": "delivered"}]})
    if request.url.path.endswith("/inboxes/11"):
        return httpx.Response(200, json={"id": 11, "name": "Telegram inbox", "channel_type": "Channel::Telegram"})
    return httpx.Response(200, json={"id": 23, "inbox_id": 11, "can_reply": True})


async def mock_adapter(adapter, handler=api_handler):
    # Retain the real client's exact URL/header construction and replace only its transport.
    client = await adapter._get_client()
    replacement = httpx.AsyncClient(base_url=client.base_url, headers=client.headers,
                                   transport=httpx.MockTransport(handler))
    await client.aclose()
    adapter._client = replacement
    return replacement


def webhook_app():
    from app.api.channel_gateway import router
    app = FastAPI()
    app.include_router(router)
    return app


def enable_replies(monkeypatch):
    from app.services import auto_reply_runtime
    monkeypatch.setattr(auto_reply_runtime, "_enabled_config", lambda: {"autoReplyEnabled": True})


def sql_rows(query):
    from app.services.crm_store import _crm_db_path
    with sqlite3.connect(_crm_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query)]


def test_config_precedence_masks_revocation_and_tenant_isolation(monkeypatch):
    monkeypatch.setenv("KELLAI_TELEGRAM_BOT_TOKEN", "environment-secret")
    monkeypatch.setenv("KELLAI_CHANNEL_ENV_TEAM_ID", str(TEAM))
    with tenant_scope(TEAM):
        config_store.save("telegram", {"bot_token": "tenant-secret"}, enabled=True, connected=True)
        assert config_store.get_field("telegram", "bot_token") == "tenant-secret"
        public = config_store.public_config("telegram")
        assert public["config"]["bot_token"] == config_store.REDACTED_VALUE
        config_store.save("telegram", public["config"])
        assert config_store.get_field("telegram", "bot_token") == "tenant-secret"
        assert config_store.get("telegram")["connected"] is True
        config_store.save("telegram", {"bot_token": ""})
        assert config_store.get_field("telegram", "bot_token") == ""
        assert config_store.get_all("telegram")["config"]["bot_token"] == ""
        config_store.save("wecom", {"secret": "corp-secret"})
        assert config_store.get_field("wework", "secret") == "corp-secret"
    with tenant_scope(TEAM + 1):
        assert config_store.get_field("telegram", "bot_token") == ""
        assert config_store.get("wework") == {}


def test_global_credentials_are_not_inherited_by_two_real_tenants(monkeypatch):
    from app.channels.telegram import TelegramAdapter
    from app.services import auth
    from app.services.crm_store import _crm_db_path
    from app.services.message_store import push_inbox
    auth.ensure_auth_schema()
    with sqlite3.connect(_crm_db_path()) as conn:
        conn.executemany("INSERT INTO kellai_teams (id,name,owner_id,created_at,updated_at) VALUES (?,?,?,?,?)",
                         [(TEAM, "one", 1, "now", "now"), (TEAM + 1, "two", 2, "now", "now")])
    # One tenant has legacy history, but two real teams still prohibit guessing ownership.
    push_inbox("telegram", contact_id="chat-1", direction="inbound", content="old", team_id=TEAM)
    monkeypatch.setenv("KELLAI_TELEGRAM_BOT_TOKEN", "server-secret")
    for team_id in (TEAM, TEAM + 1):
        with tenant_scope(team_id):
            assert config_store.get_field("telegram", "bot_token") == ""
            assert "bot_token" not in config_store.get_all("telegram")["config"]
            assert not TelegramAdapter()._is_configured()
    monkeypatch.setenv("KELLAI_CHANNEL_ENV_TEAM_ID", str(TEAM))
    with tenant_scope(TEAM):
        assert config_store.get_field("telegram", "bot_token") == "server-secret"
    with tenant_scope(TEAM + 1):
        assert not TelegramAdapter()._is_configured()
        config_store.save("telegram", {"bot_token": "own-team-token"})
        assert config_store.get_field("telegram", "bot_token") == "own-team-token"


def test_config_write_failure_is_not_reported_as_saved(monkeypatch):
    with tenant_scope(TEAM):
        config_store.save("telegram", {"bot_token": "old"})
        def reject_replace(*args, **kwargs):
            raise PermissionError("disk is read-only")
        monkeypatch.setattr(Path, "replace", reject_replace)
        with pytest.raises(PermissionError):
            config_store.save("telegram", {"bot_token": "new"})
        assert config_store.get_field("telegram", "bot_token") == "old"


@pytest.mark.asyncio
async def test_registry_scopes_cached_clients_and_rotates_credentials():
    registry = ChannelRegistry()
    with tenant_scope(TEAM):
        config_store.save("telegram", {"bot_token": "token-A"})
        first = registry.get("telegram")
        first_client = await first._get_client()
        assert "/bottoken-A/" == first_client.base_url.path
    with tenant_scope(TEAM + 1):
        config_store.save("telegram", {"bot_token": "token-B"})
        second = registry.get("telegram")
        assert second is not first
        assert "/bottoken-B/" == (await second._get_client()).base_url.path
    with tenant_scope(TEAM):
        assert registry.get("telegram") is first
        config_store.save("telegram", {"bot_token": "token-A2"})
        rotated = registry.get("telegram")
        assert rotated is not first
        assert "/bottoken-A2/" == (await rotated._get_client()).base_url.path


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "server_error"])
async def test_shared_http_never_retries_mutations(failure):
    calls = []
    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("unknown upstream outcome", request=request)
        return httpx.Response(503, json={"error": "unavailable"})
    client = BaseChannelClient()
    client._client = httpx.AsyncClient(base_url="https://provider.example", transport=httpx.MockTransport(handler))
    with pytest.raises(ChannelHTTPError) as caught:
        await client.post_json("/send", json={"text": "hello"})
    assert caught.value.delivery_state == "unknown"
    assert len(calls) == 1
    await client.close()


@pytest.mark.asyncio
async def test_shared_http_retains_safe_get_retry():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={}) if len(calls) == 1 else httpx.Response(200, json={"ok": True})
    client = BaseChannelClient()
    client._client = httpx.AsyncClient(base_url="https://provider.example", transport=httpx.MockTransport(handler))
    assert await client.get_json("/info") == {"ok": True}
    assert len(calls) == 2
    await client.close()


@pytest.mark.asyncio
async def test_wecom_token_fetch_does_not_recursively_wait_for_its_own_lock():
    from app.channels.wecom import _WeComClient
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("gettoken"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        assert request.url.params["access_token"] == "token"
        return httpx.Response(200, json={"errcode": 0, "msgid": "wecom-1"})
    client = _WeComClient("corp", "secret")
    client._client = httpx.AsyncClient(base_url="https://qyapi.weixin.qq.com", transport=httpx.MockTransport(handler))
    assert await asyncio.wait_for(client.fetch_token(), timeout=1) == "token"
    assert (await client.post_with_token("/cgi-bin/message/send", {"text": "hello"}))["msgid"] == "wecom-1"
    assert len(requests) == 2
    await client.close()


@pytest.mark.asyncio
async def test_chatwoot_real_request_contract_and_accepted_not_delivered():
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer api-secret-test"
        return api_handler(request)
    with tenant_scope(TEAM):
        adapter = configured()
        await mock_adapter(adapter, handler)
        result = await adapter.send_message(TARGET, "回复正文", idempotency_key="request-1")
        assert result["success"] is True and result["message_id"] == "91"
        assert result["delivery_state"] == "accepted"
        assert [r.method for r in requests] == ["GET", "POST"]
        posted = json.loads(requests[-1].content)
        assert posted == {"content": "回复正文", "message_type": "outgoing", "private": False,
                          "content_type": "text", "echo_id": "request-1",
                          "content_attributes": {"kellai_request_id": "request-1"}}
        assert (await adapter.test_connection(team_id=TEAM))["verification_level"] == "authenticated"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "server_error", "malformed", "missing_id"])
async def test_chatwoot_uncertain_post_is_not_retried_or_reported_delivered(failure):
    posts = []
    def handler(request):
        if request.method != "POST":
            return api_handler(request)
        posts.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("unknown upstream outcome", request=request)
        if failure == "server_error":
            return httpx.Response(502, json={})
        return httpx.Response(200, text="not json") if failure == "malformed" else httpx.Response(200, json={})
    with tenant_scope(TEAM):
        adapter = configured()
        await mock_adapter(adapter, handler)
        result = await adapter.send_message(TARGET, "hello")
        assert not result["success"] and result["delivery_state"] == "unknown"
        assert result["retryable"] is False and result["definitely_not_sent"] is False
        assert len(posts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["foreign_target", "foreign_inbox", "reply_window", "rejected"])
async def test_chatwoot_blocks_unbound_conversations_and_explicit_rejections(failure):
    posts = []
    def handler(request):
        if request.method == "POST":
            posts.append(request)
            return httpx.Response(403, json={"error": "forbidden"})
        if failure == "foreign_inbox":
            return httpx.Response(200, json={"id": 23, "inbox_id": 12})
        if failure == "reply_window":
            return httpx.Response(200, json={"id": 23, "inbox_id": 11, "can_reply": False})
        return api_handler(request)
    with tenant_scope(TEAM):
        adapter = configured()
        await mock_adapter(adapter, handler)
        target = f"chatwoot:{GATEWAY_ID}:8:11:23" if failure == "foreign_target" else TARGET
        result = await adapter.send_message(target, "hello")
        assert result["delivery_state"] == "failed" and result["definitely_not_sent"] is True
        assert len(posts) == (1 if failure == "rejected" else 0)


@pytest.mark.asyncio
async def test_signed_webhook_replay_creates_one_inbox_message_customer_and_job(monkeypatch):
    from app.services.message_store import list_inbox
    enable_replies(monkeypatch)
    with tenant_scope(TEAM):
        configured()
    raw, headers = signed(message_payload())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app()), base_url="http://test") as client:
        for _ in range(2):
            response = await client.post(f"/api/kellai/webhook/chatwoot/{TEAM}", content=raw, headers=headers)
            assert response.status_code == 200, response.text
    rows = list_inbox("chatwoot", include_consumed=True, team_id=TEAM)
    assert len(rows) == 1 and rows[0]["consumed"] == 1
    assert rows[0]["contact_id"] == TARGET
    assert len(sql_rows("SELECT * FROM kellai_messages")) == 1
    jobs = sql_rows("SELECT * FROM kellai_auto_reply_jobs")
    assert len(jobs) == 1 and jobs[0]["team_id"] == TEAM
    assert list_inbox("chatwoot", include_consumed=True, team_id=TEAM + 1) == []


@pytest.mark.asyncio
async def test_historical_webhook_is_persisted_without_automatic_reply(monkeypatch):
    from app.services import auto_reply_runtime
    from app.services.message_store import list_inbox
    enable_replies(monkeypatch)
    with tenant_scope(TEAM):
        configured()
    original_timestamp = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    # The webhook is signed now, but the provider message itself is historical.
    raw, headers = signed(message_payload(created_at=original_timestamp))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app()), base_url="http://test") as client:
        response = await client.post(f"/api/kellai/webhook/chatwoot/{TEAM}", content=raw, headers=headers)
        assert response.status_code == 200, response.text
    inbox = list_inbox("chatwoot", include_consumed=True, team_id=TEAM)
    assert len(inbox) == 1 and inbox[0]["consumed"] == 1
    messages = sql_rows("SELECT * FROM kellai_messages")
    assert len(messages) == 1 and messages[0]["team_id"] == TEAM
    assert json.loads(messages[0]["metadata_json"])["provider_created_at"] == original_timestamp
    assert auto_reply_runtime.runtime_status(team_id=TEAM)["counts"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["bad_signature", "stale", "foreign_account", "foreign_inbox", "foreign_conversation", "wrong_tenant"])
async def test_invalid_webhooks_fail_before_persistence(failure):
    from app.services.message_store import list_inbox
    with tenant_scope(TEAM):
        configured()
    changes = {"foreign_account": {"account": {"id": 8}}, "foreign_inbox": {"inbox": {"id": 12}},
               "foreign_conversation": {"conversation": {"id": 23, "inbox_id": 12}}}.get(failure, {})
    raw, headers = signed(message_payload(**changes),
                          secret="wrong" if failure == "bad_signature" else CONFIG["webhook_secret"],
                          timestamp=int(time.time()) - 600 if failure == "stale" else None)
    team = TEAM + 1 if failure == "wrong_tenant" else TEAM
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app()), base_url="http://test") as client:
        response = await client.post(f"/api/kellai/webhook/chatwoot/{team}", content=raw, headers=headers)
        assert response.status_code in {401, 403}
    assert list_inbox("chatwoot", include_consumed=True, team_id=TEAM) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"private": True}, {"message_type": "outgoing"}, {"message_type": "activity"}])
async def test_webhook_notes_and_outgoing_echoes_do_not_create_reply_jobs(changes):
    from app.services.message_store import list_inbox
    with tenant_scope(TEAM):
        configured()
    raw, headers = signed(message_payload(**changes))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app()), base_url="http://test") as client:
        response = await client.post(f"/api/kellai/webhook/chatwoot/{TEAM}", content=raw, headers=headers)
        assert response.status_code == 200
        assert "ignored" in response.json()
    assert list_inbox("chatwoot", include_consumed=True, team_id=TEAM) == []


@pytest.mark.asyncio
async def test_enqueue_failure_keeps_inbound_durable_for_retry(monkeypatch):
    from app.services import auto_reply_runtime
    from app.services.message_store import list_inbox
    enable_replies(monkeypatch)
    with tenant_scope(TEAM):
        configured()
    original = auto_reply_runtime.enqueue_message
    def fail_enqueue(message):
        raise RuntimeError("simulated queue failure")
    monkeypatch.setattr(auto_reply_runtime, "enqueue_message", fail_enqueue)
    raw, headers = signed(message_payload())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app()), base_url="http://test") as client:
        first = await client.post(f"/api/kellai/webhook/chatwoot/{TEAM}", content=raw, headers=headers)
        assert first.status_code == 200
        assert list_inbox("chatwoot", team_id=TEAM)[0]["consumed"] == 0
        monkeypatch.setattr(auto_reply_runtime, "enqueue_message", original)
        second = await client.post(f"/api/kellai/webhook/chatwoot/{TEAM}", content=raw, headers=headers)
        assert second.status_code == 200
    assert list_inbox("chatwoot", team_id=TEAM) == []
    assert len(sql_rows("SELECT * FROM kellai_messages")) == 1
    assert len(sql_rows("SELECT * FROM kellai_auto_reply_jobs")) == 1


@pytest.mark.asyncio
async def test_real_status_lookup_reconciles_outbox_and_survives_lookup_failure():
    from app.channels.base import UnifiedMessage
    from app.services.message_store import list_inbox
    from app.services.outbound_delivery import dispatch, get_delivery
    from app.services.chatwoot_gateway import RECEIPT_CHANNEL
    fail_lookup = True
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/messages") and request.method == "GET" and fail_lookup:
            return httpx.Response(503, json={})
        return api_handler(request)
    with tenant_scope(TEAM):
        adapter = configured()
        await mock_adapter(adapter, handler)
        message = UnifiedMessage(id="local", customer_id=1, channel_type="chatwoot",
                                 contact_id=TARGET, contact_name="test", direction="outbound",
                                 content="hello", metadata={"team_id": TEAM}, created_at="2026-11-21T10:00:00Z")
        result = await dispatch(message, idempotency_key="receipt-test", team_id=TEAM,
                                sender=lambda: adapter.send_message(message.contact_id, message.content,
                                                                    idempotency_key="receipt-test"))
        assert result["status"] == "accepted"
    raw, headers = signed(message_payload(event="message_updated", id=91, message_type="outgoing",
                                          content_attributes={"kellai_request_id": "receipt-test"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app()), base_url="http://test") as client:
        first = await client.post(f"/api/kellai/webhook/chatwoot/{TEAM}", content=raw, headers=headers)
        assert first.status_code == 200
        assert len(list_inbox(RECEIPT_CHANNEL, team_id=TEAM)) == 1
        assert get_delivery("receipt-test", team_id=TEAM)["provider_state"] == "accepted"
        fail_lookup = False
        second = await client.post(f"/api/kellai/webhook/chatwoot/{TEAM}", content=raw, headers=headers)
        assert second.status_code == 200
    assert list_inbox(RECEIPT_CHANNEL, team_id=TEAM) == []
    assert get_delivery("receipt-test", team_id=TEAM)["provider_state"] == "delivered"
    lookups = [r for r in requests if r.url.path.endswith("/messages") and r.method == "GET"]
    assert all(dict(r.url.params) == {"after": "91", "before": "92"} for r in lookups)
    assert len([r for r in requests if r.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_ecommerce_stubs_never_send_or_claim_connected():
    registry = ChannelRegistry()
    channels = {entry["channel_type"]: entry for entry in registry.list_channels()}
    assert len(channels) == 13
    with tenant_scope(TEAM):
        for kind in ("taobao", "jd", "pdd", "alibaba"):
            adapter = registry.get(kind)
            assert channels[kind]["capabilities"]["send"] is False
            assert (await adapter.send_message("buyer", "hello"))["definitely_not_sent"] is True
            assert (await adapter.test_connection(team_id=TEAM))["connected"] is False
    assert channels["telegram"]["capabilities"]["receive"] is False
    assert channels["chatwoot"]["capabilities"]["receive"] is True
    assert all(entry["capabilities"]["live_verified"] is False for entry in channels.values())


@pytest.mark.asyncio
async def test_suite_authorization_reuses_existing_tenant_token_for_internal_member(monkeypatch):
    from app.channels.wecom import WeComAdapter, _WeComClient
    from app.services import wework_suite
    from app.services.crm_store import _crm_db_path
    wework_suite.ensure_schema()
    with sqlite3.connect(_crm_db_path()) as conn:
        conn.execute("INSERT INTO kellai_wework_authorizations "
                     "(team_id,auth_corpid,permanent_code_enc,agent_id,authorized_at,updated_at) "
                     "VALUES (?,?,?,?,?,?)", (TEAM, "corp-suite", "not-decrypted-by-this-path", "1001", "now", "now"))
    fetched = []
    async def get_token(team):
        fetched.append(team)
        return "suite-corp-access-token"
    monkeypatch.setattr(wework_suite, "get_corp_access_token", get_token)
    sent = []
    def handler(request):
        sent.append(request)
        assert request.url.params["access_token"] == "suite-corp-access-token"
        payload = json.loads(request.content)
        assert payload["agentid"] == 1001 and payload["touser"] == "member-userid"
        return httpx.Response(200, json={"errcode": 0, "msgid": "suite-message-1"})
    async def http_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, transport=httpx.MockTransport(handler))
        return self._client
    monkeypatch.setattr(_WeComClient, "_get_client", http_client)
    with tenant_scope(TEAM):
        result = await WeComAdapter().send_message("member-userid", "hello")
        assert result["success"] and result["delivery_state"] == "accepted"
        assert result["message_id"] == "suite-message-1"
    assert fetched == [TEAM] and len(sent) == 1
    with tenant_scope(TEAM + 1):
        assert not (await WeComAdapter().send_message("member-userid", "hello"))["success"]
    assert len(sent) == 1


def test_native_douyin_target_is_resolved_before_server_send(monkeypatch):
    from app.channels.capabilities import resolve_send_capability
    from app.channels.douyin import DouyinAdapter
    monkeypatch.setattr(DouyinAdapter, "_resolve_desktop_target", lambda **kwargs: {
        "source": "douyin_web_portal", "contact_name": "test",
    })
    with tenant_scope(TEAM):
        capability = resolve_send_capability("douyin", contact_id="contact-1", customer_id=1, team_id=TEAM)
        assert capability["transport"] == "desktop" and capability["requires_desktop_execution"] is True
        assert capability["send"] is False and capability["definitely_not_sent"] is True


def test_douyin_shared_oauth_app_requires_service_mode_or_explicit_owner(monkeypatch):
    from app.services import douyin_channel
    for key in ("KELLAI_DOUYIN_BRIDGE_KEY", "KELLAI_WECOM_BRIDGE_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_KEY", "service-app")
    monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_SECRET", "service-secret")
    monkeypatch.setenv("KELLAI_DOUYIN_MINIAPP_SECRET", "service-miniapp-secret")
    with tenant_scope(TEAM):
        assert douyin_channel.client_key() == ""
        assert douyin_channel.client_secret() == ""
        assert douyin_channel.miniapp_secret() == ""
        assert douyin_channel._stored_app_config() == {}
        with pytest.raises(douyin_channel.DouyinChannelError):
            douyin_channel.save_app_config(next_client_key="tenant-app", next_client_secret="tenant-secret")
    # The bridge owns a common OAuth application; account access tokens remain tenant-owned.
    monkeypatch.setenv("KELLAI_DOUYIN_BRIDGE_KEY", "service-bridge-authentication-key")
    for team in (TEAM, TEAM + 1):
        with tenant_scope(team):
            assert douyin_channel.client_key() == "service-app"
            assert douyin_channel.client_secret() == "service-secret"
    with tenant_scope(TEAM):
        config_store.save("douyin", {"client_secret": "tenant-first"})
        config_store.save("douyin", {"app_secret": ""})
        assert douyin_channel.client_secret() == ""
        assert config_store.get_field("douyin", "client_secret") == ""
        assert config_store.get_all("douyin")["config"]["app_secret"] == ""
    with tenant_scope(TEAM + 1):
        assert douyin_channel.client_secret() == "service-secret"


def test_douyin_stored_service_app_is_not_read_by_unbound_tenant(monkeypatch):
    from app.services import douyin_channel
    monkeypatch.setenv("KELLAI_DOUYIN_STORAGE_KEY", "independent-stable-encryption-key")
    for key in ("KELLAI_DOUYIN_BRIDGE_KEY", "KELLAI_WECOM_BRIDGE_KEY", "KELLAI_DOUYIN_CLIENT_KEY",
                "KELLAI_DOUYIN_APP_ID", "KELLAI_DOUYIN_CLIENT_SECRET", "KELLAI_DOUYIN_APP_SECRET"):
        monkeypatch.delenv(key, raising=False)
    douyin_channel.save_app_config(next_client_key="stored-service-app", next_client_secret="stored-service-secret")
    with tenant_scope(TEAM):
        assert douyin_channel.client_key() == ""
        assert douyin_channel.client_secret() == ""
    monkeypatch.setenv("KELLAI_DOUYIN_BRIDGE_KEY", "bridge-auth-key")
    with tenant_scope(TEAM):
        assert douyin_channel.client_key() == "stored-service-app"
        assert douyin_channel.client_secret() == "stored-service-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["wework", "wechat", "phone", "douyin", "miniprogram", "telegram", "line", "whatsapp"])
async def test_unconfigured_adapters_return_definite_failure_before_transport(kind, monkeypatch):
    with tenant_scope(TEAM):
        adapter = ChannelRegistry().get(kind)
        monkeypatch.setattr(adapter, "_is_configured", lambda: False)
        result = await adapter.send_message("recipient", "hello", team_id=TEAM)
        assert result["success"] is False
        assert result["delivery_state"] == "failed" and result["definitely_not_sent"] is True


@pytest.mark.asyncio
async def test_wechat_never_redirects_a_personal_target_to_the_fixed_bot_group(monkeypatch):
    from app.channels.wechat import WeChatAdapter
    from unittest.mock import AsyncMock
    with tenant_scope(TEAM):
        config_store.save("wechat", {"bot_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret"})
        adapter = WeChatAdapter()
        bot = AsyncMock()
        monkeypatch.setattr(adapter, "_send_via_bot", bot)
        result = await adapter.send_message("someone-openid", "hello")
        assert not result["success"] and result["definitely_not_sent"]
        bot.assert_not_awaited()


@pytest.mark.asyncio
async def test_chatwoot_old_contact_cannot_be_used_after_gateway_rotation():
    with tenant_scope(TEAM):
        configured()
        config_store.save("chatwoot", {"base_url": "https://another-gateway.example"})
        adapter = ChannelRegistry().get("chatwoot")
        result = await adapter.send_message(TARGET, "hello")
        assert result["delivery_state"] == "failed" and result["definitely_not_sent"]
        assert adapter._client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["accepted", "unknown", "failed", "mismatched_id", "timeout", "http_403", "http_503"])
async def test_douyin_remote_bridge_preserves_idempotency_and_provider_receipts(monkeypatch, outcome):
    from app.services import douyin_channel
    calls = []
    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["client_request_id"] == "same-request-id"
        assert body["team_id"] == TEAM
        assert request.headers["x-kellai-douyin-bridge-key"] == "bridge-key"
        if outcome == "timeout":
            raise httpx.ReadTimeout("ACK lost", request=request)
        if outcome.startswith("http_"):
            return httpx.Response(int(outcome[5:]), json={"error": "rejected"})
        status = outcome if outcome in {"accepted", "failed", "unknown"} else "accepted"
        receipt = {"request_id": "wrong-id" if outcome == "mismatched_id" else "same-request-id",
                   "status": status, "success": status == "accepted", "provider_state": status,
                   "message_id": "delivery:cloud-local-id", "provider_message_id": "provider-22",
                   "channel_result": {"error": "known failure" if status == "failed" else ""}}
        return httpx.Response(200, json={"success": status == "accepted", "data": {
            "message_id": "provider-22", "receipt": receipt,
        }})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(douyin_channel.httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(handler),
    ))
    monkeypatch.setattr(douyin_channel, "remote_bridge_config", lambda: {
        "base_url": "https://bridge.example", "bridge_key": "bridge-key",
    })
    result = await douyin_channel.remote_send_message(team_id=TEAM, contact_id="member", content="hello",
                                                       idempotency_key="same-request-id", customer_id=1)
    assert len(calls) == 1
    if outcome == "accepted":
        assert result["success"] is True and result["message_id"] == "provider-22"
        assert result["delivery_state"] == "accepted"
    elif outcome in {"failed", "http_403"}:
        assert result["success"] is False and result["definitely_not_sent"] is True
        assert result["delivery_state"] == "failed"
    else:
        assert result["success"] is False and result["definitely_not_sent"] is False
        assert result["delivery_state"] == "unknown"
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_douyin_adapter_forwards_same_key_and_internal_bridge_cannot_loop(monkeypatch):
    from app.channels import douyin as module
    from unittest.mock import AsyncMock
    adapter = module.DouyinAdapter()
    monkeypatch.setattr(adapter, "_is_configured", lambda: True)
    monkeypatch.setattr(adapter, "_resolve_desktop_target", lambda **kwargs: None)
    monkeypatch.setattr(adapter, "_resolve_reply_context", lambda **kwargs: {})
    monkeypatch.setattr(module, "remote_bridge_enabled", lambda: True)
    remote = AsyncMock(return_value={"success": True, "message_id": "provider-1", "delivery_state": "accepted"})
    monkeypatch.setattr(module, "remote_send_message", remote)
    with tenant_scope(TEAM):
        await adapter.send_message("member", "hello", team_id=TEAM, idempotency_key="same-key")
        assert remote.await_args.kwargs["idempotency_key"] == "same-key"
        remote.reset_mock()
        monkeypatch.setattr(module, "access_context", AsyncMock(return_value={"access_token": "own-token", "open_id": "owner"}))
        adapter._client = httpx.AsyncClient(base_url="https://open.douyin.com", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": {"error_code": 0, "server_msg_id": "official-id"}}),
        ))
        result = await adapter.send_message("member", "hello", team_id=TEAM,
                                             idempotency_key="same-key", _bridge_local_execution=True)
        assert result["success"] is True and result["message_id"] == "official-id"
        remote.assert_not_awaited()
        await adapter.close()
        monkeypatch.setattr(adapter, "_resolve_desktop_target", lambda **kwargs: {"source": "manual", "contact_name": "test"})
        result = await adapter.send_message("member", "hello", team_id=TEAM, _bridge_local_execution=True)
        assert result["definitely_not_sent"] is True and result["error"] == "requires_desktop_execution"
