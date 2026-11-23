"""Official Douyin OAuth dialect; the real Authlib state URL and encrypted store."""
import asyncio
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.channels import ChannelRegistry, config_store
from app.services import douyin_channel, connection_store
from app.services.tenant_context import tenant_scope


def token_data(open_id="own", **overrides):
    return {"data": {"error_code": 0, "access_token": "provider-secret", "refresh_token": "refresh-secret",
        "open_id": open_id, "expires_in": 3600, "refresh_expires_in": 7200,
        "scope": "user_info,enterprise.im", **overrides}}


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    def factory(**kwargs):
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(douyin_channel.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_oauth_state_single_use_form_protocol_and_identity_cannot_retarget(tool_env, monkeypatch):
    calls = []
    identity = ["own"]
    def provider(request):
        calls.append(request)
        assert request.method == "POST" and request.url == "https://open.douyin.com/oauth/access_token/"
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        fields = parse_qs(request.content.decode())
        assert fields["client_key"] == ["client"] and fields["client_secret"] == ["secret"]
        assert fields["grant_type"] == ["authorization_code"]
        return httpx.Response(200, json=token_data(identity[0]))
    mock_http(monkeypatch, provider)
    with tenant_scope(1, user_id=1):
        config_store.create_connection("douyin", {"client_key": "client", "client_secret": "secret"},
                                       connection_id="dy", auth_type="oauth2")
        started = await douyin_channel.create_oauth_url("dy", "http://127.0.0.1:8793/api/kellai/accounts/oauth/callback")
        query = parse_qs(urlsplit(started["authorization_url"]).query)
        assert query["client_key"] == ["client"] and "client_id" not in query
        assert query["state"] == [started["state"]] and "enterprise.im" in query["scope"][0]
        assert started["state"].encode() not in connection_store.database_path().read_bytes()
        done = await douyin_channel.complete_oauth(state=started["state"], code="one-use-code")
        assert done["connected"] and "provider-secret" not in json.dumps(done)
        with pytest.raises(douyin_channel.DouyinChannelError):
            await douyin_channel.complete_oauth(state=started["state"], code="one-use-code")
        assert len(calls) == 1
        identity[0] = "other"
        second = await douyin_channel.create_oauth_url("dy", started["callback_url"])
        with pytest.raises(douyin_channel.DouyinChannelError, match="原连接不同"):
            await douyin_channel.complete_oauth(state=second["state"], code="wrong-account")
        stored = config_store.get_connection("dy", include_secrets=True)
        assert stored["config"]["external_account_id"] == "own"
        assert stored["config"]["oauth_token"]["open_id"] == "own"


@pytest.mark.asyncio
async def test_expired_or_edited_or_foreign_state_never_exchanges_code(tool_env, monkeypatch):
    def forbidden(request):
        pytest.fail("invalid authorization transaction contacted the provider")
    mock_http(monkeypatch, forbidden)
    with pytest.raises(douyin_channel.DouyinChannelError):
        await douyin_channel.complete_oauth(state="d.999."+"n"*43, code="anything")
    assert not (tool_env / "tenants/999").exists()
    with tenant_scope(1, user_id=1):
        item = config_store.create_connection("douyin", {"client_key": "client", "client_secret": "secret"}, connection_id="dy")
        started = await douyin_channel.create_oauth_url("dy", "http://127.0.0.1:8793/api/kellai/accounts/oauth/callback")
        with connection_store.database(write=True) as db:
            db.execute("UPDATE connection_oauth_sessions SET expires_at=0")
        with pytest.raises(douyin_channel.DouyinChannelError):
            await douyin_channel.complete_oauth(state=started["state"], code="expired")
        started = await douyin_channel.create_oauth_url("dy", started["callback_url"])
        config_store.update_connection("dy", {"client_key": "different-client"}, expected_version=item["version"])
        with pytest.raises(connection_store.ConnectionConflict):
            await douyin_channel.complete_oauth(state=started["state"], code="stale")


@pytest.mark.asyncio
async def test_refresh_is_versioned_and_official_send_and_userinfo_bind_same_open_id(tool_env, monkeypatch):
    calls = []
    def provider(request):
        calls.append(request)
        if request.url.path == "/oauth/refresh_token/":
            fields = parse_qs(request.content.decode())
            assert fields == {"client_key": ["client"], "grant_type": ["refresh_token"], "refresh_token": ["old-refresh"]}
            return httpx.Response(200, json=token_data())
        assert request.headers["access-token"] == "provider-secret"
        if request.url.path == "/enterprise/im/message/send/":
            assert request.url.params["open_id"] == "own"
            payload = json.loads(request.content)
            assert payload["to_user_id"] == "visitor" and json.loads(payload["content"]) == {"text": "Hi"}
            return httpx.Response(200, json={"data": {"error_code": 0, "server_msg_id": "official-id"}})
        assert request.url.path == "/oauth/userinfo/" and request.method == "POST"
        assert json.loads(request.content) == {"open_id": "own", "access_token": "provider-secret"}
        return httpx.Response(200, json={"data": {"error_code": 0, "open_id": "own"}})
    mock_http(monkeypatch, provider)
    with tenant_scope(1):
        item = config_store.create_connection("douyin", {"client_key": "client", "client_secret": "secret",
            "external_account_id": "own", "oauth_token": {"access_token": "expired", "refresh_token": "old-refresh",
                "expires_at": 1, "refresh_expires_at": int(time.time())+3600, "open_id": "own", "scope": "enterprise.im,user_info"}},
            connection_id="dy", auth_type="oauth2")
        with config_store.connection_scope("dy"):
            assert (await douyin_channel.access_context(1))["access_token"] == "provider-secret"
            updated = config_store.get_connection("dy")
            assert updated["version"] == item["version"]+1
            adapter = ChannelRegistry().get("douyin", "dy")
            assert (await adapter.send_message("visitor", "Hi"))["message_id"] == "official-id"
            tested = await adapter.test_connection()
            assert tested["connected"] and tested["config_version"] == updated["version"]
        assert len(calls) == 3


@pytest.mark.asyncio
async def test_missing_permission_or_expired_refresh_blocks_before_provider_send(tool_env, monkeypatch):
    def forbidden(request):
        pytest.fail("ungranted messaging capability contacted a provider")
    mock_http(monkeypatch, forbidden)
    with tenant_scope(1):
        config_store.create_connection("douyin", {"client_key": "client", "client_secret": "secret", "external_account_id": "own",
            "oauth_token": {"access_token": "user-only", "scope": "user_info", "open_id": "own", "expires_at": int(time.time())+3600}},
            connection_id="dy")
        adapter = ChannelRegistry().get("douyin", "dy")
        result = await adapter.send_message("visitor", "Hi")
        assert result["definitely_not_sent"] and result["delivery_state"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["cancelled", "abandoned"])
async def test_uncertain_refresh_is_not_replayed_after_restart_or_cancellation(tool_env, monkeypatch, interruption):
    started = asyncio.Event()
    calls = []
    async def provider(request):
        calls.append(request)
        started.set()
        await asyncio.Event().wait()
    mock_http(monkeypatch, provider)
    with tenant_scope(1):
        config_store.create_connection("douyin", {"client_key": "client", "client_secret": "secret",
            "external_account_id": "own", "oauth_token": {"access_token": "expired", "refresh_token": "once",
            "expires_at": 1, "refresh_expires_at": int(time.time())+3600, "open_id": "own", "scope": "enterprise.im"}},
            connection_id="dy", auth_type="oauth2")
        with config_store.connection_scope("dy"):
            if interruption == "abandoned":
                with connection_store.database(write=True) as database:
                    database.execute("INSERT INTO connection_refresh_leases VALUES(?,?,?)", ("dy", "dead-process", 1))
                with pytest.raises(connection_store.ConnectionUnavailable):
                    await douyin_channel.access_context(1)
            else:
                running = asyncio.create_task(douyin_channel.access_context(1))
                await started.wait()
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await running
            assert config_store.get_connection("dy")["status"] == "requires_reconnect"
            with pytest.raises(connection_store.ConnectionUnavailable):
                await douyin_channel.access_context(1)
            assert len(calls) == (1 if interruption == "cancelled" else 0)
