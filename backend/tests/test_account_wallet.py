"""Wallet boundaries, migration and the real Authlib protocol implementation."""
import asyncio
import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from cryptography.fernet import Fernet

from app.channels import config_store
from app.channels.base import ChannelAdapter
from app.channels.registry import ChannelRegistry
from app.services import connection_store as store, credential_vault, oauth_client
from app.services.tenant_context import tenant_data_root, tenant_scope


@pytest.fixture
def wallet(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KELLAI_VAULT_KEY", Fernet.generate_key().decode())
    with tenant_scope(1, user_id=7):
        yield tmp_path


def test_secret_storage_roundtrip_redaction_and_ownership(wallet):
    first = config_store.create_connection("telegram", {
        "bot_token": "secret-first", "headers": {"Authorization": "Bearer hidden"},
        "nested": [{"password": "nested-secret"}], "public_label": "sales",
    })
    second = config_store.create_connection("telegram", {"bot_token": "secret-second"})
    assert first["config"]["bot_token"] == "********"
    assert first["config"]["headers"] == "********"
    assert first["config"]["nested"][0]["password"] == "********"
    assert b"secret-first" not in store.database_path().read_bytes()
    # Reopen through a new database connection: persistence does not depend on memory.
    assert store.get_connection(first["connection_id"], include_secrets=True)["config"]["bot_token"] == "secret-first"
    with config_store.connection_scope(first["connection_id"]):
        assert config_store.get_field("telegram", "bot_token") == "secret-first"
        with pytest.raises(PermissionError):
            config_store.get_field("wechat", "app_secret")
        with pytest.raises(PermissionError):
            with config_store.connection_scope(second["connection_id"]):
                pass
    with pytest.raises(store.ConnectionUnavailable):
        config_store.get_field("telegram", "bot_token")
    with store.database(write=True) as database:
        encrypted = database.execute("SELECT config_enc FROM connections WHERE connection_id=?",
                                     (first["connection_id"],)).fetchone()[0]
        database.execute("UPDATE connections SET config_enc=? WHERE connection_id=?",
                         (encrypted, second["connection_id"]))
    with pytest.raises(credential_vault.VaultUnavailable):
        store.get_connection(second["connection_id"], include_secrets=True)
    assert store.get_connection(second["connection_id"])["status"] == "vault_locked"


def test_same_id_in_other_workspace_does_not_reveal_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KELLAI_VAULT_KEY", Fernet.generate_key().decode())
    with tenant_scope(1):
        config_store.create_connection("telegram", {"bot_token": "owner-one"}, connection_id="account")
    with tenant_scope(2):
        assert config_store.list_connections() == []
        with pytest.raises(KeyError):
            config_store.get_connection("account")
        config_store.create_connection("telegram", {"bot_token": "owner-two"}, connection_id="account")
        assert config_store.get_connection("account", include_secrets=True)["config"]["bot_token"] == "owner-two"


def test_no_environment_resurrection_and_masked_edit(wallet, monkeypatch):
    monkeypatch.setenv("KELLAI_TELEGRAM_BOT_TOKEN", "server-secret-must-not-be-used")
    item = config_store.create_connection("telegram", {"bot_token": "first"})
    item = config_store.update_connection(item["connection_id"], {"bot_token": "********"},
                                          expected_version=item["version"])
    assert config_store.get_connection(item["connection_id"], include_secrets=True)["config"]["bot_token"] == "first"
    item = config_store.update_connection(item["connection_id"], {"bot_token": ""}, expected_version=item["version"])
    with config_store.connection_scope(item["connection_id"]):
        assert config_store.get_field("telegram", "bot_token") == ""
    with pytest.raises(store.ConnectionConflict):
        config_store.update_connection(item["connection_id"], {"bot_token": "stale"}, expected_version=1)


def test_legacy_migration_removes_old_secret_source_and_is_repeatable(wallet):
    path = tenant_data_root() / "channel_configs.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"telegram": {"name": "old", "enabled": True,
                                             "connected": True, "config": {"bot_token": "legacy-secret"}}}))
    assert config_store.migrate_legacy() == {"migrated": 1}
    assert not path.exists()
    item = config_store.get_connection("legacy-telegram", include_secrets=True)
    assert item["config"]["bot_token"] == "legacy-secret"
    assert not item["connected"]  # Old UI claims are not remote verification.
    assert config_store.migrate_legacy() == {"migrated": 0}
    assert len(config_store.list_connections()) == 1


def test_migration_failure_preserves_source_and_rolls_back(wallet, monkeypatch):
    path = tenant_data_root() / "channel_configs.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"telegram": {"config": {"bot_token": "keep-me"}}}))
    monkeypatch.setenv("KELLAI_VAULT_KEY", "invalid-key")
    with pytest.raises(credential_vault.VaultUnavailable):
        config_store.migrate_legacy()
    assert path.exists()
    with store.database() as database:
        assert database.execute("SELECT COUNT(*) FROM connections").fetchone()[0] == 0


def test_root_legacy_file_requires_proven_owner_before_migration(wallet):
    path = wallet / "channel_configs.json"
    path.write_text(json.dumps({"telegram": {"config": {"bot_token": "legacy-root"}}}))
    with pytest.raises(store.ConnectionUnavailable, match="归属不明"):
        config_store.list_connections()
    assert path.exists()
    with sqlite3.connect(str(wallet / "kellai.db")) as database:
        database.execute("CREATE TABLE kellai_messages (team_id INTEGER)")
        database.execute("INSERT INTO kellai_messages VALUES (1)")
    assert config_store.migrate_legacy() == {"migrated": 1}
    assert not path.exists()
    assert store.get_connection("legacy-telegram", include_secrets=True)["config"]["bot_token"] == "legacy-root"


def test_explicit_workspace_does_not_assign_ambiguous_root_credentials(wallet, monkeypatch):
    path = wallet / "channel_configs.json"
    path.write_text(json.dumps({"telegram": {"config": {"bot_token": "unassigned"}}}))
    monkeypatch.setenv("KELLAI_WORKSPACE_ID", "1")
    with sqlite3.connect(str(wallet / "kellai.db")) as database:
        database.execute("CREATE TABLE kellai_messages (team_id INTEGER)")
        database.executemany("INSERT INTO kellai_messages VALUES (?)", [(1,), (2,)])
    with pytest.raises(store.ConnectionUnavailable, match="归属不明"):
        config_store.list_connections()
    assert path.exists()


def test_missing_key_and_insecure_keyring_fail_closed(wallet, monkeypatch):
    item = store.create_connection("telegram", {"bot_token": "secret"})
    monkeypatch.delenv("KELLAI_VAULT_KEY")
    import keyring
    from keyring.backends.null import Keyring
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    with pytest.raises(credential_vault.VaultUnavailable):
        store.get_connection(item["connection_id"], include_secrets=True)
    with pytest.raises(credential_vault.VaultUnavailable):
        store.create_connection("telegram", {"bot_token": "another"})
    disabled = store.update_connection(item["connection_id"], enabled=False)
    assert disabled["enabled"] is False
    assert not disabled["connected"]


def test_native_backend_is_selected_from_real_keyring_chainer(wallet, monkeypatch):
    import keyring
    from keyring.backends.chainer import ChainerBackend
    monkeypatch.delenv("KELLAI_VAULT_KEY")
    values = {}
    class Native:
        __module__ = "keyring.backends.SecretService"
        priority = 1
        def get_password(self, service, name):
            return values.get((service, name))
        def set_password(self, service, name, value):
            values[(service, name)] = value
    class Plaintext:
        priority = 10
        def get_password(self, *args):
            raise AssertionError("An insecure chained backend must never read the master key")
        def set_password(self, *args):
            raise AssertionError("An insecure chained backend must never write the master key")
    monkeypatch.setattr(ChainerBackend, "backends", [Plaintext(), Native()])
    monkeypatch.setattr(keyring, "get_keyring", lambda: ChainerBackend())
    item = store.create_connection("telegram", {"bot_token": "native-vault-secret"})
    assert values
    assert store.get_connection(item["connection_id"], include_secrets=True)["config"]["bot_token"] == "native-vault-secret"
    assert b"native-vault-secret" not in store.database_path().read_bytes()


class EchoAdapter(ChannelAdapter):
    channel_type = "wallet_test"
    async def send_message(self, contact_id, content, **kwargs):
        await asyncio.sleep(0)
        return {"value": config_store.get_field(self.channel_type, "bot_token")}
    async def receive_messages(self, since="", limit=50):
        return []
    async def get_contacts(self, keyword="", limit=80):
        return []
    async def test_connection(self, **kwargs):
        return {"connected": True}


@pytest.mark.asyncio
async def test_bound_adapters_isolate_accounts_and_refuse_revoked_instances(wallet):
    registry = ChannelRegistry()
    registry.register("wallet_test", EchoAdapter)
    one = store.create_connection("wallet_test", {"bot_token": "one"})
    two = store.create_connection("wallet_test", {"bot_token": "two"})
    first = registry.get("wallet_test", one["connection_id"])
    second = registry.get("wallet_test", two["connection_id"])
    results = await asyncio.gather(first.send_message("id", "content"), second.send_message("id", "content"))
    assert results == [{"value": "one"}, {"value": "two"}]
    store.update_connection(one["connection_id"], enabled=False)
    with pytest.raises(store.ConnectionUnavailable):
        await first.send_message("id", "content")
    await registry.close_all()


@pytest.mark.asyncio
async def test_retired_client_closes_after_inflight_operation_finishes(wallet):
    started, release = asyncio.Event(), asyncio.Event()
    closed = []
    class InflightAdapter(EchoAdapter):
        async def send_message(self, contact_id, content, **kwargs):
            started.set()
            await release.wait()
            assert not closed
            return {"success": True}
        async def close(self):
            closed.append(True)
    registry = ChannelRegistry()
    registry.register("wallet_test", InflightAdapter)
    item = store.create_connection("wallet_test", {})
    adapter = registry.get("wallet_test", item["connection_id"])
    task = asyncio.create_task(adapter.send_message("contact", "message"))
    await started.wait()
    await registry.invalidate(connection_id=item["connection_id"])
    assert not closed
    release.set()
    assert (await task)["success"]
    assert closed == [True]


def oauth_account():
    return store.create_connection("oauth2", {"provider": "github", "client_id": "test-client",
                                              "client_secret": "test-client-secret"}, auth_type="oauth2")


def oauth_transport(monkeypatch, handler):
    original = oauth_client._client
    transport = httpx2.MockTransport(handler)
    monkeypatch.setattr(oauth_client, "_client", lambda config, **kwargs: original(config, transport=transport, **kwargs))


@pytest.mark.asyncio
async def test_real_authlib_pkce_exchange_and_one_time_callback(wallet, monkeypatch):
    requests = []
    async def handler(request):
        requests.append(request)
        if request.url.path.endswith("access_token"):
            return httpx2.Response(200, json={"access_token": "oauth-access", "refresh_token": "oauth-refresh",
                                              "token_type": "Bearer", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer oauth-access"
        return httpx2.Response(200, json={"id": 42, "login": "verified-user"})
    oauth_transport(monkeypatch, handler)
    item = oauth_account()
    flow = await oauth_client.start(item["connection_id"], "http://127.0.0.1:8100" + oauth_client.CALLBACK_PATH)
    params = parse_qs(urlsplit(flow["authorization_url"]).query)
    assert params["code_challenge_method"] == ["S256"]
    result = await oauth_client.complete(state=flow["state"], code="provider-code")
    token_request = parse_qs(requests[0].content.decode())
    challenge = base64.urlsafe_b64encode(hashlib.sha256(token_request["code_verifier"][0].encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [challenge]
    assert token_request["code"] == ["provider-code"]
    assert result["config"]["external_account_id"] == "42"
    assert result["config"]["oauth_token"] == "********"
    assert result["connected"]
    assert b"oauth-refresh" not in store.database_path().read_bytes()
    with pytest.raises(store.ConnectionUnavailable):
        await oauth_client.complete(state=flow["state"], code="provider-code")
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["expired", "wrong_state", "config_changed"])
async def test_oauth_invalid_transactions_never_exchange_token(wallet, monkeypatch, failure):
    async def forbidden(request):
        raise AssertionError("invalid OAuth transaction made a network request")
    oauth_transport(monkeypatch, forbidden)
    item = oauth_account()
    flow = await oauth_client.start(item["connection_id"], "http://127.0.0.1:8100" + oauth_client.CALLBACK_PATH)
    if failure == "expired":
        with store.database(write=True) as database:
            database.execute("UPDATE connection_oauth_sessions SET expires_at=0")
    elif failure == "config_changed":
        store.update_connection(item["connection_id"], {"client_id": "replacement"})
    else:
        flow["state"] += "tampered"
    with pytest.raises(store.ConnectionUnavailable):
        await oauth_client.complete(state=flow["state"], code="code")


@pytest.mark.asyncio
async def test_refresh_rotates_tokens_once_and_disconnect_clears_them(wallet, monkeypatch):
    token_requests = []
    async def handler(request):
        token_requests.append(parse_qs(request.content.decode()))
        return httpx2.Response(200, json={"access_token": "new-access", "refresh_token": "rotated-refresh",
                                          "expires_in": 3600, "token_type": "Bearer"})
    oauth_transport(monkeypatch, handler)
    item = oauth_account()
    store.update_connection(item["connection_id"], {"oauth_token": {
        "access_token": "old-access", "refresh_token": "old-refresh", "token_type": "Bearer",
        "expires_at": time.time()-10}}, connected=True)
    result = await oauth_client.active_token(item["connection_id"])
    assert result["refresh_token"] == "rotated-refresh"
    assert (await oauth_client.active_token(item["connection_id"]))["access_token"] == "new-access"
    assert len(token_requests) == 1
    assert token_requests[0]["refresh_token"] == ["old-refresh"]
    response = await oauth_client.disconnect(item["connection_id"])
    assert response["local_disabled"] and not response["provider_revocation_supported"]
    record = store.get_connection(item["connection_id"], include_secrets=True)
    assert record["config"]["oauth_token"] == {}
    with pytest.raises(store.ConnectionUnavailable):
        await oauth_client.active_token(item["connection_id"])


def test_browser_reference_is_not_reported_as_verified(wallet):
    item = store.create_connection("wechat", {"session_ref": "external-session"}, auth_type="browser")
    assert item["status"] == "executor_required" and not item["connected"]
    item = store.update_connection(item["connection_id"], connected=True)
    assert item["status"] == "executor_required" and not item["connected"]


def test_callback_destinations_are_not_arbitrary():
    for value in ["http://evil.example/api/kellai/accounts/oauth/callback", "https://trusted.example/other",
                  "https://user:password@trusted.example/api/kellai/accounts/oauth/callback"]:
        with pytest.raises(store.ConnectionUnavailable):
            oauth_client.validate_callback_url(value)


def test_changing_oauth_issuer_discards_old_token_before_any_request(wallet):
    item = oauth_account()
    store.update_connection(item["connection_id"], {"oauth_token": {"access_token": "github-secret"},
                                                    "external_account_id": "original-user"}, connected=True)
    changed = store.update_connection(item["connection_id"], {"provider": "google"})
    assert changed["status"] == "requires_reconnect"
    assert not changed["connected"]
    config = store.get_connection(item["connection_id"], include_secrets=True)["config"]
    assert config["oauth_token"] == {}
    assert config["external_account_id"] == "original-user"


def test_channel_catalog_exposes_explicit_auth_types(wallet):
    rows = {row["channel_type"]: row for row in ChannelRegistry().list_channels()}
    assert rows["oauth2"]["auth_types"] == ["oauth2"]
    assert rows["douyin"]["auth_types"] == ["credentials", "oauth2"]
    assert rows["telegram"]["config_schema"]["properties"]["bot_token"]["writeOnly"]


def test_account_removal_preserves_history_identity_but_erases_live_credentials(wallet):
    item = store.create_connection("telegram", {"bot_token": "removed-secret"}, name="Historical account")
    assert store.delete_connection(item["connection_id"])
    assert store.delete_connection(item["connection_id"])
    assert store.list_connections() == []
    tombstone = store.get_connection(item["connection_id"])
    assert tombstone["name"] == "Historical account"
    assert tombstone["status"] == "deleted" and tombstone["config"] == {}
    with store.database() as database:
        assert database.execute("SELECT config_enc FROM connections").fetchone()[0] == ""
    with pytest.raises(store.ConnectionUnavailable):
        store.get_connection(item["connection_id"], include_secrets=True)
    with pytest.raises(store.ConnectionUnavailable):
        store.update_connection(item["connection_id"], enabled=True)


@pytest.mark.asyncio
async def test_refresh_lease_prevents_parallel_rotating_token_requests(wallet, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def handler(request):
        calls.append(request)
        started.set()
        await release.wait()
        return httpx2.Response(200, json={"access_token": "new", "refresh_token": "rotation",
                                          "expires_in": 3600, "token_type": "Bearer"})
    oauth_transport(monkeypatch, handler)
    item = oauth_account()
    store.update_connection(item["connection_id"], {"oauth_token": {
        "access_token": "old", "refresh_token": "once", "token_type": "Bearer", "expires_at": 1}})
    first = asyncio.create_task(oauth_client.active_token(item["connection_id"]))
    await started.wait()
    with pytest.raises(store.ConnectionConflict):
        await oauth_client.active_token(item["connection_id"])
    release.set()
    assert (await first)["refresh_token"] == "rotation"
    assert len(calls) == 1


def test_account_api_and_browser_callback_complete_without_operator_token(wallet, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.auth import create_operator_session
    captured = []
    async def handler(request):
        captured.append(request)
        if request.url.path.endswith("access_token"):
            return httpx2.Response(200, json={"access_token": "callback-token", "token_type": "Bearer"})
        return httpx2.Response(200, json={"id": "verified-account", "login": "account-name"})
    oauth_transport(monkeypatch, handler)
    token = create_operator_session()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    client = TestClient(app, base_url="http://127.0.0.1:8790")
    assert client.get("/api/kellai/accounts").status_code == 401
    created = client.post("/api/kellai/accounts", headers=headers, json={
        "channel_type": "oauth2", "auth_type": "oauth2", "config": {
            "provider": "github", "client_id": "client", "client_secret": "hidden-client-secret"}})
    assert created.status_code == 200, created.text
    assert "hidden-client-secret" not in created.text
    identifier = created.json()["data"]["connection_id"]
    start = client.post(f"/api/kellai/accounts/{identifier}/oauth/start", headers=headers)
    assert start.status_code == 200, start.text
    flow = start.json()["data"]
    # Browser callback intentionally carries provider code/state, not the local operator bearer.
    callback = client.get(oauth_client.CALLBACK_PATH, params={"state": flow["state"], "code": "one-time-code"})
    assert callback.status_code == 200, callback.text
    assert "callback-token" not in callback.text
    assert callback.headers["cache-control"] == "no-store"
    readback = client.get(f"/api/kellai/accounts/{identifier}", headers=headers)
    assert readback.json()["data"]["connected"]
    assert "callback-token" not in readback.text
    assert client.get(oauth_client.CALLBACK_PATH, params={"state": flow["state"], "code": "one-time-code"}).status_code == 400
    assert len(captured) == 2
    denied = client.get(oauth_client.CALLBACK_PATH, params={"state": flow["state"], "error": "access_denied"})
    assert denied.status_code == 400
    assert denied.headers["cache-control"] == "no-store"
    assert denied.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_foreign_callback_cannot_create_workspace(wallet):
    with pytest.raises(store.ConnectionUnavailable, match="工作区"):
        await oauth_client.complete(state="999." + "A" * 43, code="code")
    assert not (wallet / "tenants" / "999").exists()


@pytest.mark.asyncio
async def test_identity_check_does_not_send_old_token_to_changed_provider(wallet, monkeypatch):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx2.Response(200, json={"sub": "account"})
    oauth_transport(monkeypatch, handler)
    item = oauth_account()
    identifier = item["connection_id"]
    store.update_connection(identifier, {"oauth_token": {"access_token": "issuer-secret", "token_type": "Bearer"},
                                         "external_account_id": "account"}, connected=True)
    original = oauth_client.active_token
    async def changed_after_token_read(connection_id):
        token = await original(connection_id)
        store.update_connection(connection_id, {"provider": "google"})
        return token
    monkeypatch.setattr(oauth_client, "active_token", changed_after_token_read)
    with store.connection_scope(identifier):
        with pytest.raises(store.ConnectionConflict):
            await oauth_client.OAuthAccountAdapter().test_connection()
    assert calls == []


@pytest.mark.parametrize("channel_type,auth_type", [("oauth2", "oauth2"), ("douyin", "oauth2")])
def test_account_api_cannot_install_or_replace_provider_authorization(wallet, channel_type, auth_type):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.auth import create_operator_session
    client = TestClient(app, base_url="http://127.0.0.1:8793")
    headers = {"Authorization": "Bearer " + create_operator_session()["access_token"]}
    base = {"provider": "github", "client_id": "client"} if channel_type == "oauth2" else {
        "client_key": "client", "client_secret": "secret"}
    fake = {"access_token": "caller-supplied-token", "scope": "enterprise.im", "open_id": "other"}
    rejected = client.post("/api/kellai/accounts", headers=headers, json={
        "channel_type": channel_type, "auth_type": auth_type,
        "config": {**base, "oauth_token": fake, "external_account_id": "other"}})
    assert rejected.status_code == 400
    created = config_store.create_connection(channel_type, base, auth_type=auth_type)
    identifier = created["connection_id"]
    verified = store.update_connection(identifier, {"oauth_token": {"access_token": "original-secret"},
        "external_account_id": "original", "account_name": "Original"}, connected=True)
    for forged in ({"oauth_token": fake}, {"external_account_id": "other"}, {"account_name": "Forged"}):
        response = client.patch(f"/api/kellai/accounts/{identifier}", headers=headers,
            json={"expected_version": verified["version"], "config": forged})
        assert response.status_code == 400
    unchanged = store.get_connection(identifier, include_secrets=True)
    assert unchanged["version"] == verified["version"]
    assert unchanged["config"]["external_account_id"] == "original"
    assert unchanged["config"]["oauth_token"]["access_token"] == "original-secret"
    # The editor round-trips public metadata and secret masks; those are no-ops.
    edited = client.patch(f"/api/kellai/accounts/{identifier}", headers=headers, json={
        "expected_version": verified["version"], "config": verified["config"], "name": "Renamed"})
    assert edited.status_code == 200, edited.text
    assert "original-secret" not in edited.text
    assert store.get_connection(identifier, include_secrets=True)["config"]["oauth_token"]["access_token"] == "original-secret"


def test_account_api_rejects_auth_types_outside_channel_contract(wallet):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.auth import create_operator_session
    client = TestClient(app, base_url="http://127.0.0.1:8793")
    headers = {"Authorization": "Bearer " + create_operator_session()["access_token"]}
    result = client.post("/api/kellai/accounts", headers=headers, json={
        "channel_type": "telegram", "auth_type": "oauth2", "config": {"bot_token": "secret"}})
    assert result.status_code == 400
    assert store.list_connections() == []


def test_douyin_disconnect_erases_old_authorization_and_preserves_identity(wallet):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.auth import create_operator_session
    client = TestClient(app, base_url="http://127.0.0.1:8793")
    headers = {"Authorization": "Bearer " + create_operator_session()["access_token"]}
    item = store.create_connection("douyin", {"client_key": "client", "client_secret": "secret",
        "external_account_id": "original", "oauth_token": {"access_token": "old-secret",
        "refresh_token": "old-refresh", "open_id": "original", "scope": "enterprise.im"}}, auth_type="oauth2")
    identifier = item["connection_id"]
    response = client.post(f"/api/kellai/accounts/{identifier}/disconnect", headers=headers)
    assert response.status_code == 200, response.text
    disconnected = store.get_connection(identifier, include_secrets=True)
    assert disconnected["config"]["oauth_token"] == {}
    assert disconnected["config"]["external_account_id"] == "original"
    assert not disconnected["enabled"] and not disconnected["connected"]
    # Editing and enabling cannot bring a revoked platform token back.
    edited = client.patch(f"/api/kellai/accounts/{identifier}", headers=headers,
        json={"expected_version": disconnected["version"], "enabled": True, "config": {"scope": "enterprise.im"}})
    assert edited.status_code == 200, edited.text
    assert store.get_connection(identifier, include_secrets=True)["config"]["oauth_token"] == {}


@pytest.mark.asyncio
async def test_cancelled_refresh_requires_reconnect_before_reusing_rotating_secret(wallet, monkeypatch):
    started = asyncio.Event()
    calls = []
    async def provider(request):
        calls.append(request)
        started.set()
        await asyncio.Event().wait()
    oauth_transport(monkeypatch, provider)
    item = oauth_account()
    identifier = item["connection_id"]
    store.update_connection(identifier, {"oauth_token": {"access_token": "old", "refresh_token": "rotating",
        "expires_at": 1, "token_type": "Bearer"}}, connected=True)
    first = asyncio.create_task(oauth_client.active_token(identifier))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    record = store.get_connection(identifier)
    assert record["status"] == "requires_reconnect" and not record["connected"]
    store.update_connection(identifier, {"public_label": "changed"}, enabled=True)
    with pytest.raises(store.ConnectionUnavailable):
        await oauth_client.active_token(identifier)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_abandoned_refresh_lease_never_replays_rotating_secret(wallet, monkeypatch):
    async def forbidden(request):
        pytest.fail("An abandoned refresh exchange cannot safely reuse the old rotating token")
    oauth_transport(monkeypatch, forbidden)
    item = oauth_account()
    identifier = item["connection_id"]
    store.update_connection(identifier, {"oauth_token": {"access_token": "old", "refresh_token": "rotating",
        "expires_at": 1, "token_type": "Bearer"}}, connected=True)
    with store.database(write=True) as database:
        database.execute("INSERT INTO connection_refresh_leases VALUES (?,?,?)", (identifier, "crashed-worker", 1))
    with pytest.raises(store.ConnectionUnavailable):
        await oauth_client.active_token(identifier)
    assert store.get_connection(identifier)["status"] == "requires_reconnect"
    with store.database() as database:
        assert database.execute("SELECT COUNT(*) FROM connection_refresh_leases").fetchone()[0] == 0


def test_locked_vault_revocation_cannot_be_undone_by_editing_metadata(wallet, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.auth import create_operator_session
    key = os.environ["KELLAI_VAULT_KEY"]
    item = config_store.create_connection("douyin", {"client_key": "client", "client_secret": "secret",
        "external_account_id": "original", "oauth_token": {"access_token": "old-secret",
        "open_id": "original", "scope": "enterprise.im"}}, auth_type="oauth2")
    identifier = item["connection_id"]
    client = TestClient(app, base_url="http://127.0.0.1:8793")
    headers = {"Authorization": "Bearer " + create_operator_session()["access_token"]}
    monkeypatch.setenv("KELLAI_VAULT_KEY", Fernet.generate_key().decode())
    assert client.post(f"/api/kellai/accounts/{identifier}/disconnect", headers=headers).status_code == 200
    monkeypatch.setenv("KELLAI_VAULT_KEY", key)
    disabled = store.get_connection(identifier)
    result = client.patch(f"/api/kellai/accounts/{identifier}", headers=headers, json={
        "expected_version": disabled["version"], "enabled": True, "config": {"public_label": "edited"}})
    assert result.status_code == 200, result.text
    with pytest.raises(store.ConnectionUnavailable):
        store.require_active(identifier)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["rename", "disconnect", "reauthorize"])
async def test_refresh_cannot_overwrite_concurrent_account_changes(wallet, monkeypatch, change):
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def provider(request):
        calls.append(request)
        started.set()
        await release.wait()
        return httpx2.Response(200, json={"access_token": "late-access", "refresh_token": "late-refresh",
            "expires_in": 3600, "token_type": "Bearer"})
    oauth_transport(monkeypatch, provider)
    item = oauth_account()
    identifier = item["connection_id"]
    store.update_connection(identifier, {"oauth_token": {"access_token": "old", "refresh_token": "rotating",
        "expires_at": 1, "token_type": "Bearer"}}, connected=True)
    running = asyncio.create_task(oauth_client.active_token(identifier))
    await started.wait()
    if change == "disconnect":
        await oauth_client.disconnect(identifier)
    elif change == "reauthorize":
        store.update_connection(identifier, {"oauth_token": {"access_token": "new-grant", "expires_at": time.time()+3600}},
                                connected=True, expected_version=store.get_connection(identifier)["version"])
    else:
        store.update_connection(identifier, name="Renamed during refresh")
    release.set()
    with pytest.raises(store.ConnectionConflict):
        await running
    current = store.get_connection(identifier, include_secrets=True)
    assert current["config"].get("oauth_token", {}).get("access_token") != "late-access"
    if change == "reauthorize":
        assert (await oauth_client.active_token(identifier))["access_token"] == "new-grant"
    else:
        with pytest.raises(store.ConnectionUnavailable):
            await oauth_client.active_token(identifier)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_confirmed_refresh_commit_survives_process_exit_before_lease_cleanup(wallet, monkeypatch):
    item = oauth_account()
    identifier = item["connection_id"]
    store.update_connection(identifier, {"oauth_token": {"access_token": "expired", "refresh_token": "previous",
        "expires_at": 1, "token_type": "Bearer"}}, connected=True)
    result = subprocess.run([sys.executable, "-c", """
import os
import sys
from app.services import connection_store as store
from app.services.tenant_context import tenant_scope
with tenant_scope(1):
    item = store.get_connection(sys.argv[1])
    with store.refresh_lease(sys.argv[1], expected_version=item["version"]):
        store.update_connection(sys.argv[1], {"oauth_token": {"access_token": "committed-access",
            "refresh_token": "committed-refresh", "expires_at": 1, "token_type": "Bearer"}},
            connected=True, expected_version=item["version"])
        os._exit(23)
""", identifier], check=False, capture_output=True, timeout=10)
    assert result.returncode == 23, result.stderr.decode()
    assert store.get_connection(identifier, include_secrets=True)["config"]["oauth_token"]["refresh_token"] == "committed-refresh"
    with store.database() as database:
        assert database.execute("SELECT COUNT(*) FROM connection_refresh_leases").fetchone()[0] == 0
    calls = []
    async def provider(request):
        calls.append(parse_qs(request.content.decode()))
        assert calls[0]["refresh_token"] == ["committed-refresh"]
        return httpx2.Response(200, json={"access_token": "next-access", "refresh_token": "next-refresh",
            "expires_in": 3600, "token_type": "Bearer"})
    oauth_transport(monkeypatch, provider)
    assert (await oauth_client.active_token(identifier))["access_token"] == "next-access"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_disconnect_after_failed_refresh_persists_revoked_status(wallet):
    item = oauth_account()
    identifier = item["connection_id"]
    store.update_connection(identifier, connected=False, status="requires_reconnect")
    await oauth_client.disconnect(identifier)
    with store.database() as database:
        assert store._row(database, identifier)["status"] == "revoked"
    disabled = store.get_connection(identifier)
    store.update_connection(identifier, {"public_label": "edited"}, enabled=True,
                            expected_version=disabled["version"])
    assert store.get_connection(identifier)["status"] == "revoked"


def test_connection_test_cannot_settle_a_pending_token_refresh(wallet):
    item = oauth_account()
    identifier = item["connection_id"]
    with store.database(write=True) as database:
        database.execute("INSERT INTO connection_refresh_leases VALUES (?,?,?)", (identifier, "active-worker", int(time.time())+120))
    store.update_connection(identifier, connected=True, expected_version=item["version"])
    with store.database() as database:
        assert database.execute("SELECT holder FROM connection_refresh_leases WHERE connection_id=?", (identifier,)).fetchone()[0] == "active-worker"


@pytest.mark.asyncio
async def test_delayed_account_test_cannot_allow_replay_of_inflight_rotating_token(wallet, monkeypatch):
    import httpx
    from app.main import app
    from app.services.auth import create_operator_session
    clock = [10_000.0]
    monkeypatch.setattr(oauth_client.time, "time", lambda: clock[0])
    identity_started, identity_release = asyncio.Event(), asyncio.Event()
    refresh_started, refresh_release = asyncio.Event(), asyncio.Event()
    refreshes = []
    async def provider(request):
        if request.url.path.endswith("access_token"):
            refreshes.append(request)
            refresh_started.set()
            await refresh_release.wait()
            return httpx2.Response(200, json={"access_token": "late-access", "refresh_token": "late-refresh",
                "expires_in": 3600, "token_type": "Bearer"})
        identity_started.set()
        await identity_release.wait()
        return httpx2.Response(200, json={"id": "owner", "login": "Verified owner"})
    oauth_transport(monkeypatch, provider)
    item = oauth_account()
    identifier = item["connection_id"]
    store.update_connection(identifier, {"external_account_id": "owner", "oauth_token": {
        "access_token": "original", "refresh_token": "rotating-once", "token_type": "Bearer",
        "expires_at": clock[0] + 120}}, connected=True)
    headers = {"Authorization": "Bearer " + create_operator_session()["access_token"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8793") as client:
        testing = asyncio.create_task(client.post(f"/api/kellai/accounts/{identifier}/test", headers=headers))
        await asyncio.wait_for(identity_started.wait(), 2)
        clock[0] += 100
        refreshing = asyncio.create_task(oauth_client.active_token(identifier))
        await asyncio.wait_for(refresh_started.wait(), 2)
        identity_release.set()
        tested = await asyncio.wait_for(testing, 2)
        refresh_release.set()
        with pytest.raises(store.ConnectionConflict):
            await refreshing
        with pytest.raises(store.ConnectionUnavailable):
            await oauth_client.active_token(identifier)
        assert len(refreshes) == 1
        assert tested.status_code == 409
        assert store.get_connection(identifier)["status"] == "requires_reconnect"
