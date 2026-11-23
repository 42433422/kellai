"""Protocol v2: local handoff, explicit accounts and one durable send path."""
import hashlib
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.main import app
from app.channels import ChannelRegistry, config_store
from app.channels.base import UnifiedMessage
from app.services import auth, message_store, outbound_delivery, xcmax_integration
from app.services.tenant_context import tenant_scope

PREFIX = "/api/kellai"
GATEWAY = PREFIX + "/integrations/xcmax"


def local_headers():
    return {"Authorization": "Bearer " + auth.create_operator_session()["access_token"]}


@pytest.mark.asyncio
async def test_lock_revokes_original_operator_session_but_preserves_other_session_and_grant(tool_env):
    first, second = local_headers(), local_headers()
    host = grant()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8793") as client:
        assert (await client.post(PREFIX + "/auth/lock", headers=first)).status_code == 200
        assert (await client.get(PREFIX + "/accounts", headers=first)).status_code == 401
        assert (await client.post(PREFIX + "/auth/lock", headers=first)).status_code == 401
        assert (await client.get(PREFIX + "/accounts", headers=second)).status_code == 200
        assert (await client.get(GATEWAY + "/grant-status", headers=host)).status_code == 200


def grant(scopes=None, *, version=2):
    token = "host-test-token-with-enough-entropy"
    xcmax_integration._write({"version": version, "connection": {
        "connection_id": "paired-host", "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "protocol_version": version, "authorized_scopes": scopes or sorted(xcmax_integration.SCOPES),
        "team_id": 1,
    }})
    return {"Authorization": "Bearer " + token}


def account(kind="telegram", *, cid="first", config=None):
    with tenant_scope(1):
        return config_store.create_connection(kind, config or {"bot_token": "secret-" + cid}, connection_id=cid)


def target(cid="first", address="target"):
    with tenant_scope(1):
        return message_store.register_contact(connection_id=cid, channel_type="telegram", contact_id=address,
                                              contact_name="可视化联系人")


def body(contact, *, key="request", **changes):
    return {"connection_id": contact["connection_id"], "customer_id": contact["customer_id"],
            "channel_type": contact["channel_type"], "contact_id": contact["contact_id"],
            "content": "approved by host", "client_request_id": key, **changes}


@pytest.mark.asyncio
async def test_single_use_handoff_is_only_local_session_entry(tool_env, monkeypatch):
    pending = {"request_id": "once", "authorization_secret": "S" * 48, "protocol_version": 2,
               "requested_scopes": [{"id": "messages.read"}], "expires_at": "2099-01-01T00:00:00Z"}
    calls = []

    def host(path, *, method="GET", data=None):
        calls.append((path, method, data))
        if path.endswith("/handoff"):
            if sum(item[0].endswith("/handoff") for item in calls) > 1:
                raise RuntimeError("handoff already claimed")
            return {"success": True, "data": pending}
        if path.endswith("/status"):
            return {"success": True, "data": {"state": "pending", "pending": pending}}
        assert path.endswith("/approve")
        assert data["authorization_secret"] == pending["authorization_secret"]
        assert data["protocol_version"] == 2
        return {"success": True, "data": {"state": "connected"}}

    monkeypatch.setattr(xcmax_integration, "_xcmax_request", host)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8793") as client:
        denied = await client.post(PREFIX + "/auth/xcmax-desktop")
        assert denied.status_code == 403 and not calls
        login = await client.post(PREFIX + "/auth/xcmax-desktop", headers={"X-Kellai-Desktop-Handoff": "1"})
        assert login.status_code == 200
        data = login.json()
        assert auth.verify_token(data["access_token"])["role"] == "owner"
        assert pending["authorization_secret"] not in login.text
        assert data["access_token"].encode() not in (tool_env / "kellai.db").read_bytes()
        headers = {"Authorization": "Bearer " + data["access_token"]}
        visible = await client.get(GATEWAY + "/pending", headers=headers)
        assert visible.json()["data"]["request_id"] == "once"
        assert pending["authorization_secret"] not in visible.text
        assert (await client.post(PREFIX + "/auth/xcmax-desktop", headers={"X-Kellai-Desktop-Handoff": "1"})).status_code == 409
        approved = await client.post(GATEWAY + "/approve", headers=headers,
                                     json={"request_id": "once", "accepted_scopes": ["messages.read"]})
        assert approved.status_code == 200
        supplied = calls[-1][2]["access_token"]
        assert supplied not in xcmax_integration._store_path().read_text()
        assert xcmax_integration.authorize_access_token(supplied, "messages.read")["actor"]["team_id"] == 1
        with pytest.raises(Exception):
            xcmax_integration.authorize_access_token(supplied, "messages.send")
        assert xcmax_integration.pending_authorization() is None


@pytest.mark.asyncio
async def test_local_revoke_fences_an_inflight_host_approval(tool_env, monkeypatch):
    requested, release = threading.Event(), threading.Event()
    request_id = "approval-overlapped-by-revoke"
    xcmax_integration._HANDOFFS[xcmax_integration._handoff_key(request_id)] = {
        "request_id": request_id, "authorization_secret": "S" * 48,
        "workspace_id": 1, "received_at": time.time(),
        "requested_scopes": [{"id": "messages.send"}],
    }
    issued = []

    def host(path, *, method="GET", data=None):
        assert path.endswith("/approve")
        issued.append(data["access_token"])
        requested.set()
        assert release.wait(5), "test did not release the host acknowledgement"
        return {"success": True, "data": {"state": "connected"}}

    monkeypatch.setattr(xcmax_integration, "_xcmax_request", host)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(xcmax_integration.approve_authorization,
            request_id=request_id, accepted_scopes=["messages.send"], current_user=auth.operator())
        assert requested.wait(5)
        try:
            assert xcmax_integration.disconnect()["local_grant_revoked"]
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="本机交接已失效"):
            pending.result(timeout=5)
    assert xcmax_integration.public_status()["connected"] is False
    assert xcmax_integration.pending_authorization() is None
    with pytest.raises(Exception) as denied:
        xcmax_integration.authorize_access_token(issued[0], "messages.send")
    assert denied.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("origin,host,peer,extra", [
    ("https://evil.example", "127.0.0.1:8793", "127.0.0.1", {}),
    ("null", "127.0.0.1:8793", "127.0.0.1", {}),
    (None, "attacker.example:8793", "127.0.0.1", {}),
    (None, "127.0.0.1:8793", "203.0.113.5", {}),
    (None, "127.0.0.1:8793", "127.0.0.1", {"Sec-Fetch-Site": "cross-site"}),
])
async def test_handoff_denies_untrusted_browser_or_peer_before_host_call(tool_env, monkeypatch, origin, host, peer, extra):
    def forbidden(*args, **kwargs):
        pytest.fail("untrusted request reached the host")
    monkeypatch.setattr(xcmax_integration, "_xcmax_request", forbidden)
    headers = {"Host": host, "X-Kellai-Desktop-Handoff": "1", **extra}
    if origin is not None:
        headers["Origin"] = origin
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(peer, 4000)),
                                base_url="http://127.0.0.1:8793") as client:
        result = await client.post(PREFIX + "/auth/xcmax-desktop", headers=headers)
    assert result.status_code == 403


@pytest.mark.asyncio
async def test_tool_has_no_saas_or_unapproved_send_route_and_scopes_cannot_widen(tool_env):
    headers = local_headers()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8793") as client:
        for path in ("/auth/register", "/auth/login", "/customers", "/billing", "/ai/chat", "/messages/send",
                     "/wework/suite/callback", "/douyin/desktop/prepare"):
            assert (await client.post(PREFIX + path, json={}, headers=headers)).status_code == 404
        assert (await client.get(PREFIX + "/accounts")).status_code == 401
        assert (await client.get(GATEWAY + "/contacts", headers=grant(version=1))).status_code == 403
        read_only = grant(["messages.read"])
        assert (await client.post(GATEWAY + "/messages/send", headers=read_only, json={
            "connection_id": "unbound", "customer_id": 1, "channel_type": "telegram", "contact_id": "one",
            "content": "no", "client_request_id": "denied"})).status_code == 403
        callback = await client.get(PREFIX + "/accounts/oauth/callback?state=bad&code=bad")
        assert callback.status_code == 400  # State validation, not operator-login interception.
        preflight = await client.options(PREFIX + "/accounts/one", headers={
            "Origin": "http://localhost:1420", "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "Authorization,Content-Type"})
        assert preflight.status_code == 200 and "PATCH" in preflight.headers["access-control-allow-methods"]


@pytest.mark.asyncio
async def test_host_send_receipt_and_exact_readback_are_one_account(tool_env, monkeypatch):
    account(); account(cid="second")
    contact, other = target(), target("second")
    sent = []
    with tenant_scope(1):
        adapter = ChannelRegistry().get("telegram", "first")
    async def provider(address, text, **kwargs):
        sent.append((config_store.current_connection_id(required=True), address, text))
        return {"success": True, "message_id": "remote-81", "delivery_state": "accepted"}
    monkeypatch.setattr(adapter._adapter, "send_message", provider)
    headers = grant()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8793") as client:
        channels = (await client.get(GATEWAY + "/channels", headers=headers)).json()["data"]["channels"]
        assert {c["connection_id"] for c in channels} == {"first", "second"}
        missing = body(contact); missing.pop("connection_id")
        assert (await client.post(GATEWAY + "/messages/send", headers=headers, json=missing)).status_code == 422
        for change in ({"connection_id": "second"}, {"channel_type": "wechat"}, {"contact_id": "wrong"},
                       {"customer_id": other["customer_id"]}):
            response = await client.post(GATEWAY + "/messages/send", headers=headers, json=body(contact, **change))
            assert response.status_code == 409, response.text
        assert not sent
        first = await client.post(GATEWAY + "/messages/send", headers=headers, json=body(contact))
        assert first.status_code == 200, first.text
        receipt = first.json()["data"]
        assert receipt["status"] == "accepted" and receipt["persisted"]
        assert receipt["connection_id"] == "first" and receipt["contact_id"] == "target"
        again = (await client.post(GATEWAY + "/messages/send", headers=headers, json=body(contact))).json()["data"]
        assert again["replayed"] and len(sent) == 1
        assert (await client.post(GATEWAY + "/messages/send", headers=headers, json=body(other))).status_code == 409
        recovered = (await client.get(GATEWAY + "/messages/requests/request", headers=headers)).json()["data"]
        assert recovered["message_id"] == receipt["message_id"]
        with tenant_scope(1):
            for index in range(105):
                message_store.save_message(UnifiedMessage(id=f"later-{index}", connection_id="first",
                    channel_type="telegram", contact_id="target", contact_name="target", customer_id=contact["customer_id"],
                    direction="inbound", content="later", created_at="2099-01-01T00:00:00Z"))
        readback = await client.get(GATEWAY + f"/contacts/{contact['customer_id']}/messages", headers=headers,
            params={"connection_id": "first", "message_id": receipt["message_id"], "limit": 1})
        data = readback.json()["data"]
        assert data["connection_id"] == "first" and data["customer_id"] == contact["customer_id"]
        assert data["messages"][0]["id"] == receipt["message_id"]
        assert data["messages"][0]["connection_id"] == "first"
        empty = await client.get(GATEWAY + f"/contacts/{contact['customer_id']}/messages", headers=headers,
                                 params={"connection_id": "second", "message_id": receipt["message_id"]})
        assert empty.json()["data"]["messages"] == []


@pytest.mark.asyncio
async def test_deleted_account_erases_credentials_keeps_history_and_blocks_send(tool_env):
    account(); contact = target()
    with tenant_scope(1):
        message_store.save_message(UnifiedMessage(id="historical", connection_id="first", customer_id=contact["customer_id"],
            channel_type="telegram", contact_id="target", contact_name="target", direction="inbound", content="keep", created_at="2025-01-01"))
    headers = local_headers()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8793") as client:
        assert (await client.delete(PREFIX + "/accounts/first", headers=headers)).status_code == 200
        assert (await client.get(PREFIX + "/accounts", headers=headers)).json()["data"] == []
        history = await client.get(PREFIX + f"/contacts/{contact['customer_id']}/messages?connection_id=first", headers=headers)
        assert history.json()["data"]["messages"][0]["content"] == "keep"
        assert len((await client.get(PREFIX + "/contacts", headers=headers)).json()["data"]["contacts"]) == 1
        blocked = await client.post(GATEWAY + "/messages/send", headers=grant(), json=body(contact))
        assert blocked.status_code == 409


def test_operator_tokens_expire_and_ambiguous_workspace_fails(tool_env, monkeypatch):
    login = auth.create_operator_session()
    with sqlite3.connect(tool_env / "kellai.db") as db:
        db.execute("UPDATE kellai_tool_sessions SET expires_at=0")
    assert auth.verify_token(login["access_token"]) is None
    monkeypatch.delenv("KELLAI_WORKSPACE_ID")
    (tool_env / "tenants/1").mkdir(parents=True, exist_ok=True)
    (tool_env / "tenants/2").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="多个工作区"):
        auth.workspace_id()


def test_old_pairing_secret_migrates_to_hash_but_is_not_new_scope_authorization(tool_env):
    token = "legacy-plaintext-secret"
    xcmax_integration._write({"version": 1, "connection": {"access_token": token,
        "authorized_scopes": ["customer_profiles.read"], "protocol_version": 1}})
    with pytest.raises(Exception):
        xcmax_integration.authorize_access_token(token, "messages.read")
    assert token not in xcmax_integration._store_path().read_text()
    assert xcmax_integration._read()["connection"]["requires_reconnect"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["http://tauri.localhost", "tauri://localhost", "http://localhost:1420"])
async def test_explicit_trusted_desktop_origin_allows_cross_site_fetch(tool_env, monkeypatch, origin):
    monkeypatch.setattr(xcmax_integration, "_xcmax_request", lambda *a, **kw: {"success": True, "data": {
        "request_id": "trusted", "authorization_secret": "T" * 48, "protocol_version": 2}})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8793") as client:
        response = await client.post(PREFIX + "/auth/xcmax-desktop", headers={
            "Origin": origin, "Sec-Fetch-Site": "cross-site", "X-Kellai-Desktop-Handoff": "1"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.asyncio
async def test_grant_probe_distinguishes_revoke_from_scope_denial(tool_env, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("tool status/revoke must not call the host owner-only session API")
    monkeypatch.setattr(xcmax_integration, "_xcmax_request", forbidden)
    operator = local_headers()
    host = grant(["messages.read"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8793") as client:
        status = await client.get(GATEWAY + "/grant-status", headers=host)
        assert status.status_code == 200 and status.json()["data"]["authorized_scopes"] == ["messages.read"]
        assert (await client.get(GATEWAY + "/status", headers=operator)).json()["data"]["host_state"] == "not_checked"
        denied = await client.get(GATEWAY + "/channels", headers=host)
        assert denied.json()["detail"]["code"] == "xcmax_scope_required"
        revoked = await client.post(GATEWAY + "/disconnect", headers=operator)
        assert revoked.json()["data"] == {"local_grant_revoked": True, "host_metadata_cleared": False, "host_cleanup_required": True}
        denied = await client.get(GATEWAY + "/grant-status", headers=host)
        assert denied.status_code == 401 and denied.json()["detail"]["code"] == "xcmax_grant_revoked"
