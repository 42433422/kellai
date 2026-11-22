"""Douyin's documented OAuth dialect, scoped to a local account connection.

Authlib owns authorization URL/state construction; HTTPX only adapts Douyin's
client_key field and data-wrapped token response. No centralized bridge remains.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client

from app.channels import config_store
from app.services import connection_store as store, credential_vault
from app.services.oauth_client import validate_callback_url
from app.services.tenant_context import current_user_id, resolve_team_id, tenant_scope

DOUYIN_API_BASE = "https://open.douyin.com"


class DouyinChannelError(ValueError):
    pass


def _config() -> dict:
    return config_store.get_all("douyin")["config"]


def client_key() -> str:
    return str(_config().get("client_key") or _config().get("app_id") or "")


def client_secret() -> str:
    return str(_config().get("client_secret") or _config().get("app_secret") or "")


async def create_oauth_url(connection_id: str, redirect_uri: str) -> dict:
    redirect_uri = validate_callback_url(redirect_uri)
    item = config_store.get_connection(connection_id, include_secrets=True)
    config = item["config"]
    if item["channel_type"] != "douyin" or not config.get("client_key") or not config.get("client_secret"):
        raise DouyinChannelError("请先配置抖音 Client Key 与 Client Secret")
    owner = resolve_team_id(required=True)
    state = f"d.{owner}.{secrets.token_urlsafe(32)}"
    scope = str(config.get("scope") or "user_info,enterprise.im")
    async with AsyncOAuth2Client(client_id=config["client_key"], redirect_uri=redirect_uri,
                                  scope=scope, trust_env=False) as client:
        url, _ = client.create_authorization_url(DOUYIN_API_BASE + "/platform/oauth/connect/", state=state)
    parsed = urlsplit(url)
    query = [("client_key" if key == "client_id" else key, value) for key, value in parse_qsl(parsed.query)]
    url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
    payload = credential_vault.encrypt({"redirect_uri": redirect_uri, "state": state}, owner_id=owner,
                                       connection_id=connection_id, purpose="oauth_state")
    with store.database(write=True) as db:
        if store._row(db, connection_id)["version"] != item["version"]:
            raise store.ConnectionConflict("账号配置已变化，请重新授权")
        db.execute("DELETE FROM connection_oauth_sessions WHERE connection_id=? OR expires_at<?", (connection_id, int(time.time())))
        db.execute("INSERT INTO connection_oauth_sessions VALUES(?,?,?,?,?,?,?,0)", (
            hashlib.sha256(state.encode()).hexdigest(), connection_id, owner, current_user_id(),
            item["version"], payload, int(time.time()) + 600))
    return {"authorization_url": url, "state": state, "expires_in": 600, "callback_url": redirect_uri}


async def _token_request(path: str, fields: dict) -> dict:
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
        response = await client.post(DOUYIN_API_BASE + path, data={k: str(v) for k, v in fields.items()})
    if response.status_code >= 300:
        raise DouyinChannelError("抖音授权服务未接受请求")
    body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or str(data.get("error_code")) != "0" or not data.get("access_token"):
        raise DouyinChannelError("抖音未返回有效授权，请重新连接")
    return data


def _token(data: dict, previous: dict | None = None) -> dict:
    previous = previous or {}
    now = int(time.time())
    expiry = int(data.get("expires_in") or 0)
    if expiry <= 0 or not (data.get("open_id") or previous.get("open_id")):
        raise DouyinChannelError("抖音授权缺少账号身份或有效期")
    return {"access_token": str(data["access_token"]),
            "refresh_token": str(data.get("refresh_token") or previous.get("refresh_token") or ""),
            "open_id": str(data.get("open_id") or previous["open_id"]),
            "scope": str(data.get("scope") or previous.get("scope") or ""),
            "expires_at": now + expiry,
            "refresh_expires_at": now + int(data["refresh_expires_in"]) if data.get("refresh_expires_in")
                                  else int(previous.get("refresh_expires_at") or 0)}


async def complete_oauth(*, state: str, code: str) -> dict:
    try:
        prefix, owner_text, nonce = state.split(".", 2)
        owner = int(owner_text)
        if prefix != "d" or owner <= 0 or len(nonce) < 40 or len(state) > 256 or not code or len(code) > 4096:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise DouyinChannelError("抖音授权事务无效") from exc
    from app.services.auth import workspace_id
    if owner != workspace_id():
        raise DouyinChannelError("授权工作区不匹配")
    with tenant_scope(owner):
        digest = hashlib.sha256(state.encode()).hexdigest()
        with store.database(write=True) as db:
            session = db.execute("SELECT * FROM connection_oauth_sessions WHERE state_hash=? AND owner_id=?", (digest, owner)).fetchone()
            if not session or session["consumed"] or session["expires_at"] < int(time.time()):
                raise DouyinChannelError("授权事务已过期或已使用")
            row = store._row(db, session["connection_id"])
            if row["version"] != session["config_version"]:
                raise store.ConnectionConflict("账号配置已变化")
            state_payload = credential_vault.decrypt(session["payload_enc"], owner_id=owner,
                connection_id=session["connection_id"], purpose="oauth_state")
            if state_payload.get("state") != state:
                raise DouyinChannelError("授权事务校验失败")
            item = store._result(row, include_secrets=True)
            if item["channel_type"] != "douyin":
                raise DouyinChannelError("授权渠道不匹配")
            db.execute("UPDATE connection_oauth_sessions SET consumed=1 WHERE state_hash=?", (digest,))
        config = item["config"]
        data = await _token_request("/oauth/access_token/", {"client_key": config["client_key"],
            "client_secret": config["client_secret"], "code": code, "grant_type": "authorization_code"})
        token = _token(data)
        if config.get("external_account_id") and config["external_account_id"] != token["open_id"]:
            raise DouyinChannelError("授权账号与原连接不同，请新建账号")
        return store.update_connection(item["connection_id"], {"oauth_token": token,
            "external_account_id": token["open_id"], "account_name": token["open_id"]},
            connected=True, enabled=True, status="connected", expected_version=item["version"])


async def access_context(team_id: int) -> dict:
    resolve_team_id(team_id, required=True)
    identifier = store.current_connection_id(required=True)
    item = store.require_active(identifier, channel_type="douyin")
    token = item["config"].get("oauth_token")
    if not isinstance(token, dict) or not token.get("access_token"):
        raise DouyinChannelError("此账号尚未完成官方授权")
    if token.get("open_id") != item["config"].get("external_account_id"):
        raise DouyinChannelError("账号授权身份不一致")
    if "enterprise.im" not in set(str(token.get("scope") or "").replace(" ", ",").split(",")):
        raise DouyinChannelError("此账号未授予 enterprise.im 私信权限")
    if int(token.get("expires_at") or 0) > time.time() + 120:
        return {**token, "_connection_version": item["version"]}
    if not token.get("refresh_token") or int(token.get("refresh_expires_at") or 0) <= time.time() + 60:
        store.update_connection(identifier, connected=False, status="requires_reconnect", expected_version=item["version"])
        raise DouyinChannelError("授权已过期，请重新连接")
    holder = secrets.token_hex(16)
    with store.database(write=True) as db:
        acquired = db.execute("""INSERT INTO connection_refresh_leases VALUES(?,?,?)
            ON CONFLICT(connection_id) DO UPDATE SET holder=excluded.holder,expires_at=excluded.expires_at
            WHERE connection_refresh_leases.expires_at<?""", (identifier, holder, int(time.time()) + 60, int(time.time()))).rowcount
        if not acquired:
            raise store.ConnectionConflict("授权刷新正在进行")
        if store._row(db, identifier)["version"] != item["version"]:
            db.execute("DELETE FROM connection_refresh_leases WHERE connection_id=? AND holder=?", (identifier, holder))
            raise store.ConnectionConflict("账号配置已变化")
    try:
        data = await _token_request("/oauth/refresh_token/", {"client_key": item["config"]["client_key"],
            "grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
        updated = _token(data, token)
        if "enterprise.im" not in set(updated["scope"].replace(" ", ",").split(",")):
            raise DouyinChannelError("刷新后的授权缺少私信权限")
        if updated["open_id"] != token["open_id"]:
            raise DouyinChannelError("刷新后的账号身份不一致")
        refreshed = store.update_connection(identifier, {"oauth_token": updated}, connected=True,
                                            expected_version=item["version"])
        return {**updated, "_connection_version": refreshed["version"]}
    except Exception:
        try:
            store.update_connection(identifier, connected=False, status="requires_reconnect", expected_version=item["version"])
        except store.ConnectionConflict:
            pass
        raise
    finally:
        with store.database(write=True) as db:
            db.execute("DELETE FROM connection_refresh_leases WHERE connection_id=? AND holder=?", (identifier, holder))


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    secret = client_secret()
    if not secret or not signature or not signature.isascii():
        return False
    expected = hashlib.sha1(secret.encode() + raw_body).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())
