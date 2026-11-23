"""Authlib OAuth clients for an explicit local connection, with fixed provider endpoints."""
from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

from authlib.integrations.httpx_client import AsyncOAuth2Client

from app.channels.base import ChannelAdapter
from app.services import connection_store as store, credential_vault
from app.services.tenant_context import current_user_id, resolve_team_id, tenant_scope


PROVIDERS = {
    "github": {"authorize": "https://github.com/login/oauth/authorize",
               "token": "https://github.com/login/oauth/access_token",
               "userinfo": "https://api.github.com/user", "scope": "read:user", "subject": "id"},
    "google": {"authorize": "https://accounts.google.com/o/oauth2/v2/auth",
               "token": "https://oauth2.googleapis.com/token",
               "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
               "revoke": "https://oauth2.googleapis.com/revoke",
               "scope": "openid email profile", "subject": "sub"},
    "microsoft": {"authorize": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                  "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                  "userinfo": "https://graph.microsoft.com/v1.0/me",
                  "scope": "offline_access User.Read", "subject": "id"},
}
CALLBACK_PATH = "/api/kellai/accounts/oauth/callback"
CONFIG_SCHEMA = {
    "type": "object", "required": ["provider", "client_id"],
    "properties": {
        "provider": {"type": "string", "title": "授权服务", "enum": list(PROVIDERS)},
        "client_id": {"type": "string", "title": "OAuth Client ID"},
        "client_secret": {"type": "string", "title": "OAuth Client Secret", "writeOnly": True},
        "scope": {"type": "string", "title": "申请权限", "description": "留空使用身份读取的最小权限"},
    },
}


def validate_callback_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != CALLBACK_PATH or not parsed.hostname):
        raise store.ConnectionUnavailable("OAuth 回调地址配置无效")
    if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
        raise store.ConnectionUnavailable("OAuth 回调必须使用 HTTPS 或本机回环地址")
    return url


def _provider(config: dict) -> dict:
    provider = PROVIDERS.get(str(config.get("provider") or ""))
    if not provider:
        raise store.ConnectionUnavailable("该账号不支持标准 OAuth 授权")
    if not config.get("client_id"):
        raise store.ConnectionUnavailable("请先保存 OAuth Client ID")
    return provider


def _client(config: dict, **kwargs: Any) -> AsyncOAuth2Client:
    provider = _provider(config)
    return AsyncOAuth2Client(
        client_id=config["client_id"], client_secret=config.get("client_secret") or None,
        token_endpoint_auth_method="client_secret_post" if config.get("client_secret") else "none",
        scope=config.get("scope") or provider["scope"],
        timeout=20.0, follow_redirects=False, trust_env=False, **kwargs,
    )


async def start(connection_id: str, redirect_uri: str) -> dict[str, Any]:
    redirect_uri = validate_callback_url(redirect_uri)
    item = store.get_connection(connection_id, include_secrets=True)
    if item["auth_type"] != "oauth2" or item["channel_type"] != "oauth2":
        raise store.ConnectionUnavailable("该账号不使用标准 OAuth 授权")
    config = item["config"]
    provider = _provider(config)
    owner = resolve_team_id(required=True)
    state = f"{owner}.{secrets.token_urlsafe(32)}"
    verifier = secrets.token_urlsafe(48)
    async with _client(config, redirect_uri=redirect_uri, code_challenge_method="S256") as client:
        extra = {"access_type": "offline", "prompt": "consent"} if config["provider"] == "google" else {}
        url, returned_state = client.create_authorization_url(
            provider["authorize"], state=state, code_verifier=verifier, **extra)
    assert returned_state == state
    payload = credential_vault.encrypt(
        {"verifier": verifier, "redirect_uri": redirect_uri, "state": state},
        owner_id=owner, connection_id=connection_id, purpose="oauth_state")
    with store.database(write=True) as database:
        if store._row(database, connection_id)["version"] != item["version"]:
            raise store.ConnectionConflict("账号配置已变化，请重新发起授权")
        database.execute("DELETE FROM connection_oauth_sessions WHERE expires_at<? OR connection_id=?",
                         (int(time.time()), connection_id))
        database.execute("INSERT INTO connection_oauth_sessions VALUES (?,?,?,?,?,?,?,0)",
                         (hashlib.sha256(state.encode()).hexdigest(), connection_id, owner,
                          current_user_id(), item["version"], payload, int(time.time()) + 600))
    return {"authorization_url": url, "state": state, "expires_in": 600, "callback_url": redirect_uri}


async def complete(*, state: str, code: str) -> dict[str, Any]:
    try:
        owner_text, nonce = state.split(".", 1)
        owner = int(owner_text)
        if owner <= 0 or len(nonce) < 40 or len(state) > 256:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise store.ConnectionUnavailable("OAuth 授权事务无效") from exc
    if not code or len(code) > 4096:
        raise store.ConnectionUnavailable("OAuth 未返回有效授权码")
    from app.services.auth import workspace_id
    if owner != workspace_id():
        # Public callbacks must not create arbitrary owner directories before
        # checking their state, nor change future workspace inference.
        raise store.ConnectionUnavailable("OAuth 授权事务不属于当前工作区")
    with tenant_scope(owner):
        digest = hashlib.sha256(state.encode()).hexdigest()
        with store.database(write=True) as database:
            session = database.execute("SELECT * FROM connection_oauth_sessions WHERE state_hash=? AND owner_id=?",
                                       (digest, owner)).fetchone()
            if session is None or session["consumed"] or session["expires_at"] < int(time.time()):
                raise store.ConnectionUnavailable("OAuth 授权事务已失效，请重新连接")
            row = store._row(database, session["connection_id"])
            if row["version"] != session["config_version"]:
                raise store.ConnectionConflict("账号配置已变化，请重新连接")
            database.execute("UPDATE connection_oauth_sessions SET consumed=1 WHERE state_hash=?", (digest,))
            item = store._result(row, include_secrets=True)
            payload = credential_vault.decrypt(session["payload_enc"], owner_id=owner,
                connection_id=item["connection_id"], purpose="oauth_state")
        # Commit single consumption before any external token request. An uncertain
        # exchange is never retried with the same code/state.
        config, provider = item["config"], _provider(item["config"])
        response_url = payload["redirect_uri"] + "?" + urlencode({"state": state, "code": code})
        try:
            async with _client(config, redirect_uri=payload["redirect_uri"],
                               state=payload["state"], code_challenge_method="S256") as client:
                token = await client.fetch_token(provider["token"], authorization_response=response_url,
                                                 code_verifier=payload["verifier"])
                identity = await _identity(client, provider)
            previous = config.get("external_account_id")
            if previous and str(previous) != identity["external_account_id"]:
                raise store.ConnectionUnavailable("授权账号与原连接不同，请新增账号连接")
            return store.update_connection(item["connection_id"],
                {"oauth_token": dict(token), **identity}, connected=True, enabled=True,
                expected_version=item["version"])
        except store.ConnectionUnavailable:
            raise
        except Exception as exc:
            raise store.ConnectionUnavailable("OAuth 授权未完成，请重新连接") from exc


async def _identity(client: AsyncOAuth2Client, provider: dict) -> dict[str, str]:
    response = await client.get(provider["userinfo"])
    response.raise_for_status()
    body = response.json()
    subject = body.get(provider["subject"])
    if not subject:
        raise store.ConnectionUnavailable("服务商未返回可验证的账号身份")
    return {"external_account_id": str(subject),
            "account_name": str(body.get("login") or body.get("email") or body.get("displayName")
                                or body.get("name") or subject)}


async def active_token(connection_id: str) -> dict[str, Any]:
    item = store.require_active(connection_id, channel_type="oauth2")
    config = item["config"]
    token = config.get("oauth_token")
    if not isinstance(token, dict) or not token.get("access_token"):
        raise store.ConnectionUnavailable("账号尚未完成 OAuth 授权")
    if not token.get("expires_at") or float(token["expires_at"]) > time.time() + 60:
        return token
    if not token.get("refresh_token"):
        store.update_connection(connection_id, connected=False, status="requires_reconnect",
                                expected_version=item["version"])
        raise store.ConnectionUnavailable("账号授权已过期，请重新连接")
    try:
        provider = _provider(config)
        async with _client(config, token=token) as client:
            with store.refresh_lease(connection_id, expected_version=item["version"]):
                updated = dict(await client.refresh_token(provider["token"], refresh_token=token["refresh_token"]))
                updated.setdefault("refresh_token", token["refresh_token"])
                store.update_connection(connection_id, {"oauth_token": updated}, connected=True,
                                        expected_version=item["version"])
                return updated
    except store.ConnectionUnavailable:
        raise
    except Exception as exc:
        raise store.ConnectionUnavailable("授权刷新失败，请重新连接账号") from exc


async def disconnect(connection_id: str) -> dict[str, bool]:
    try:
        item = store.get_connection(connection_id, include_secrets=True)
    except credential_vault.VaultUnavailable:
        store.update_connection(connection_id, enabled=False, connected=False, status="revoked")
        return {"local_disabled": True, "provider_revoked": False,
                "provider_revocation_supported": False}
    config = item["config"]
    token = config.get("oauth_token") or {}
    provider = (PROVIDERS.get(str(config.get("provider") or ""), {})
                if item["channel_type"] == "oauth2" else {})
    store.update_connection(connection_id, {"oauth_token": {}}, enabled=False, connected=False, status="revoked",
                            expected_version=item["version"])
    revoked = False
    if provider.get("revoke") and isinstance(token, dict) and token.get("access_token"):
        try:
            async with _client(config) as client:
                response = await client.revoke_token(provider["revoke"],
                    token=token.get("refresh_token") or token["access_token"])
                revoked = response.status_code == 200
        except Exception:
            pass
    return {"local_disabled": True, "provider_revoked": revoked,
            "provider_revocation_supported": bool(provider.get("revoke"))}


class OAuthAccountAdapter(ChannelAdapter):
    channel_type = "oauth2"

    async def test_connection(self, **kwargs):
        identifier = store.current_connection_id(required=True)
        token = await active_token(identifier)
        item = store.get_connection(identifier, include_secrets=True)
        if item["config"].get("oauth_token") != token:
            raise store.ConnectionConflict("账号授权已变化，请重新测试")
        async with _client(item["config"], token=token) as client:
            identity = await _identity(client, _provider(item["config"]))
        if identity["external_account_id"] != item["config"].get("external_account_id"):
            raise store.ConnectionUnavailable("账号身份校验失败")
        return {"connected": True, "verification_level": "authenticated",
                "config_version": item["version"],
                "message": "账号身份读取成功；该连接仅提供授权保管，不提供消息收发"}

    async def send_message(self, contact_id: str, content: str, **kwargs):
        return {"success": False, "delivery_state": "failed", "definitely_not_sent": True,
                "error": "该授权连接没有消息发送能力"}

    async def receive_messages(self, since: str = "", limit: int = 50):
        raise store.ConnectionUnavailable("该授权连接没有消息接收能力")

    async def get_contacts(self, keyword: str = "", limit: int = 80):
        raise store.ConnectionUnavailable("该授权连接没有联系人读取能力")
