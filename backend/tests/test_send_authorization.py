"""Every provider mutation rechecks authorization after its awaited preflight."""
import asyncio
import hashlib

import httpx
import pytest

from app.channels import ChannelRegistry, config_store
from app.main import app
from app.services import auth, message_store, xcmax_integration
from app.services.tenant_context import tenant_scope


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["account", "host_grant"])
async def test_revoke_during_real_preflight_blocks_provider_post(tool_env, revocation):
    host_token = "isolated-original-host-grant"
    xcmax_integration._write({"version": 2, "connection": {"connection_id": "paired-host",
        "token_hash": hashlib.sha256(host_token.encode()).hexdigest(), "protocol_version": 2,
        "authorized_scopes": ["messages.send"], "team_id": 1}})
    headers = {"Authorization": "Bearer " + host_token}
    operator_headers = {"Authorization": "Bearer " + auth.create_operator_session()["access_token"]}
    requested, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def provider(request):
        calls.append(request)
        if request.method == "GET":
            requested.set()
            await release.wait()
            return httpx.Response(200, json={"id": 23, "inbox_id": 11, "can_reply": True})
        return httpx.Response(200, json={"id": 81, "inbox_id": 11, "conversation_id": 23})

    with tenant_scope(1):
        config_store.create_connection("chatwoot", {"base_url": "https://gateway.example", "account_id": "7",
            "inbox_id": "11", "api_access_token": "isolated-token"}, connection_id="account")
        adapter = ChannelRegistry().get("chatwoot", "account")
        settings = adapter._adapter.settings()
        adapter._adapter._client = httpx.AsyncClient(base_url=settings.base_url,
            transport=httpx.MockTransport(provider))
        contact = message_store.register_contact(connection_id="account", channel_type="chatwoot",
            contact_id=settings.target(23), contact_name="Explicit recipient")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8793") as client:
        pending = asyncio.create_task(client.post("/api/kellai/integrations/xcmax/messages/send", headers=headers,
            json={"connection_id": "account", "channel_type": "chatwoot", "customer_id": contact["customer_id"],
                  "contact_id": contact["contact_id"], "content": "approved text", "client_request_id": "original-send"}))
        try:
            await asyncio.wait_for(requested.wait(), timeout=5)
            path = ("/api/kellai/accounts/account/disconnect" if revocation == "account"
                    else "/api/kellai/integrations/xcmax/disconnect")
            assert (await client.post(path, headers=operator_headers)).status_code == 200
        finally:
            release.set()
        response = await pending
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "failed"
    assert response.json()["data"]["channel_result"]["definitely_not_sent"] is True
    assert sum(request.method == "GET" for request in calls) == 1
    assert sum(request.method == "POST" for request in calls) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,config,target,extra", [
    ("telegram", {"bot_token": "secret"}, "recipient", {}),
    ("line", {"channel_access_token": "secret"}, "recipient", {}),
    ("whatsapp", {"phone_number_id": "1234", "access_token": "secret"}, "recipient", {}),
    ("phone", {"provider": "twilio", "account_sid": "ACtest", "auth_token": "secret", "from_number": "+12025550100"}, "+12025550101", {}),
    ("phone", {"provider": "aliyun", "access_key_id": "key", "access_key_secret": "secret", "sign_name": "approved", "template_code": "SMS_123"}, "13800138000", {"template_param": {"code": "1234"}}),
    ("miniprogram", {"app_id": "app", "app_secret": "secret", "template_id": "template"}, "recipient", {"data": {"thing1": {"value": "approved"}}}),
    ("wechat", {"official_app_id": "app", "official_app_secret": "secret"}, "recipient", {}),
    ("wechat", {"bot_webhook": "https://bot.example/hook"}, "@chat", {}),
    ("wework", {"corp_id": "corp", "secret": "secret", "agent_id": "10"}, "recipient", {}),
    ("wework", {"bot_webhook": "https://bot.example/hook"}, "@chat", {}),
    ("douyin", {"client_key": "client", "client_secret": "secret", "external_account_id": "own",
        "oauth_token": {"access_token": "expired", "refresh_token": "refresh", "expires_at": 1,
                        "refresh_expires_at": 9999999999, "open_id": "own", "scope": "enterprise.im"}}, "recipient", {}),
])
async def test_all_official_senders_apply_final_guard(tool_env, monkeypatch, kind, config, target, extra):
    calls, guarded = [], []

    def provider(request):
        calls.append(request)
        if request.url.path in {"/cgi-bin/token", "/cgi-bin/gettoken"}:
            return httpx.Response(200, json={"errcode": 0, "access_token": "fresh", "expires_in": 3600})
        if request.url.path == "/oauth/refresh_token/":
            return httpx.Response(200, json={"data": {"error_code": 0, "access_token": "fresh",
                "refresh_token": "refreshed", "open_id": "own", "expires_in": 3600,
                "refresh_expires_in": 7200, "scope": "enterprise.im"}})
        pytest.fail("revoked authorization reached a provider message mutation")

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(provider), **kwargs))

    def revoked_grant():
        guarded.append(True)
        raise PermissionError("original host grant was revoked")

    with tenant_scope(1):
        config_store.create_connection(kind, config, connection_id="account")
        adapter = ChannelRegistry().get(kind, "account")
        result = await adapter.send_message(target, "approved text", before_send=revoked_grant, **extra)
        assert result["success"] is False and result["definitely_not_sent"] is True
        assert guarded == [True]
        if kind == "douyin":
            assert config_store.get_connection("account")["version"] == 2
    assert all(request.url.path in {"/cgi-bin/token", "/cgi-bin/gettoken", "/oauth/refresh_token/"} for request in calls)
