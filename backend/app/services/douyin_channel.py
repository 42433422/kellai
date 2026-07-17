"""抖音企业号授权、令牌与团队绑定。

抖音渠道分成两层凭据：
- client_key / client_secret：客来来在抖音开放平台创建的应用凭据；
- access_token / refresh_token：具体企业号授权给客来来的用户凭据。

应用凭据仍由渠道配置管理；用户令牌按客来来 team_id 加密写入统一 SQLite，
不会返回给桌面前端。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet

from app.services.crm_store import _crm_db_path


DOUYIN_API_BASE = "https://open.douyin.com"
DOUYIN_AUTHORIZE_URL = f"{DOUYIN_API_BASE}/platform/oauth/connect/"
DOUYIN_OAUTH_TTL_SECONDS = 600
DOUYIN_BRIDGE_KEYCHAIN_SERVICE = "com.kellai.douyin-bridge"


class DouyinChannelError(RuntimeError):
    """可安全返回给客户端的抖音渠道错误。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _channel_field(key: str) -> str:
    from app.channels.config_store import get_field

    return get_field("douyin", key)


def client_key() -> str:
    return (
        _channel_field("client_key")
        or _channel_field("app_id")
        or _env("KELLAI_DOUYIN_CLIENT_KEY")
        or _env("KELLAI_DOUYIN_APP_ID")
        or str(_stored_app_config().get("client_key") or "")
    )


def client_secret() -> str:
    return (
        _channel_field("client_secret")
        or _channel_field("app_secret")
        or _env("KELLAI_DOUYIN_CLIENT_SECRET")
        or _env("KELLAI_DOUYIN_APP_SECRET")
        or str(_stored_app_config().get("client_secret") or "")
    )


def miniapp_app_id() -> str:
    return (
        _channel_field("miniapp_app_id")
        or _channel_field("miniapp_appid")
        or _env("KELLAI_DOUYIN_MINIAPP_APP_ID")
        or _env("KELLAI_DOUYIN_MINIAPP_APPID")
        or str(_stored_app_config().get("miniapp_app_id") or "")
    )


def miniapp_secret() -> str:
    return (
        _channel_field("miniapp_secret")
        or _channel_field("miniapp_app_secret")
        or _env("KELLAI_DOUYIN_MINIAPP_SECRET")
        or _env("KELLAI_DOUYIN_MINIAPP_APP_SECRET")
        or str(_stored_app_config().get("miniapp_secret") or "")
    )


def oauth_scopes() -> str:
    raw = (
        _env("KELLAI_DOUYIN_SCOPES")
        or "trial.whitelist,user_info"
    )
    scopes = [item.strip() for item in raw.split(",") if item.strip()]
    return ",".join(dict.fromkeys(scopes))


def public_base_url() -> str:
    return _env("KELLAI_PUBLIC_BASE_URL").rstrip("/")


def callback_url() -> str:
    base = public_base_url()
    return f"{base}/api/kellai/channels/douyin/oauth/callback" if base else ""


def webhook_url() -> str:
    base = public_base_url()
    return f"{base}/api/kellai/webhook/douyin" if base else ""


def readiness() -> dict[str, Any]:
    missing: list[str] = []
    if not client_key():
        missing.append("client_key")
    if not client_secret():
        missing.append("client_secret")
    if not public_base_url():
        missing.append("public_base_url")
    public_https = public_base_url().startswith("https://")
    return {
        "configured": not missing and public_https,
        "missing": missing,
        "public_https": public_https,
        "callback_url": callback_url(),
        "webhook_url": webhook_url(),
        "scopes": oauth_scopes().split(",") if oauth_scopes() else [],
        "miniapp": {
            "configured": bool(miniapp_app_id() and miniapp_secret() and public_https),
            "app_id": miniapp_app_id(),
            "app_id_configured": bool(miniapp_app_id()),
            "webhook_secret_configured": bool(miniapp_secret()),
        },
        "capabilities": {
            "direct_message": "im.direct_message" in oauth_scopes().split(","),
            "group_message": "im.group_fans.create_list" in oauth_scopes().split(","),
            "miniapp_direct_message": bool(miniapp_app_id() and miniapp_secret()),
        },
    }


def _keychain_bridge_key() -> str:
    if sys.platform != "darwin" or os.environ.get("PYTEST_CURRENT_TEST"):
        return ""
    account = _env("USER")
    if not account:
        return ""
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-a",
                account,
                "-s",
                DOUYIN_BRIDGE_KEYCHAIN_SERVICE,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def remote_bridge_config() -> dict[str, str]:
    """桌面端访问公网抖音 SSOT 的桥接配置。

    优先使用抖音独立桥接密钥；为兼容现有部署，可复用已经落入 macOS
    钥匙串的企业微信远端桥接凭据。
    """
    base_url = _env("KELLAI_DOUYIN_REMOTE_BASE_URL")
    bridge_key = _env("KELLAI_DOUYIN_REMOTE_BRIDGE_KEY") or _keychain_bridge_key()
    if not base_url or not bridge_key:
        try:
            from app.services.wework_suite import remote_bridge_config as wework_bridge_config

            inherited = wework_bridge_config()
        except Exception:
            inherited = {"base_url": "", "bridge_key": ""}
        base_url = base_url or str(inherited.get("base_url") or "")
        bridge_key = bridge_key or str(inherited.get("bridge_key") or "")
    return {"base_url": base_url.rstrip("/"), "bridge_key": bridge_key}


def remote_bridge_enabled() -> bool:
    cfg = remote_bridge_config()
    return bool(cfg["base_url"] and cfg["bridge_key"])


def bridge_server_enabled() -> bool:
    return bool(_env("KELLAI_DOUYIN_BRIDGE_KEY") or _env("KELLAI_WECOM_BRIDGE_KEY"))


def verify_bridge_key(value: str) -> None:
    expected = _env("KELLAI_DOUYIN_BRIDGE_KEY") or _env("KELLAI_WECOM_BRIDGE_KEY")
    if not expected:
        raise DouyinChannelError("抖音远端桥接未启用")
    if not value or not secrets.compare_digest(expected, value.strip()):
        raise DouyinChannelError("抖音远端桥接认证失败")


async def _remote_bridge_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = remote_bridge_config()
    if not cfg["base_url"] or not cfg["bridge_key"]:
        raise DouyinChannelError("抖音远端服务未配置")
    url = f"{cfg['base_url']}/api/kellai/internal/douyin/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=payload,
                headers={"X-Kellai-Douyin-Bridge-Key": cfg["bridge_key"]},
            )
    except httpx.HTTPError as exc:
        raise DouyinChannelError("抖音远端服务暂时不可用") from exc
    try:
        body = response.json()
    except Exception as exc:
        raise DouyinChannelError(f"抖音远端服务返回非 JSON：HTTP {response.status_code}") from exc
    if response.status_code >= 400 or body.get("success") is False:
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
        raise DouyinChannelError(
            str(body.get("error") or body.get("message") or detail.get("message") or response.status_code)
        )
    data = body.get("data", body)
    return data if isinstance(data, dict) else {"data": data}


async def remote_readiness() -> dict[str, Any]:
    data = await _remote_bridge_request("GET", "readiness")
    data["mode"] = "remote_ssot"
    return data


async def remote_save_app_config(
    *,
    next_client_key: str,
    next_client_secret: str,
    next_miniapp_app_id: str = "",
    next_miniapp_secret: str = "",
) -> dict[str, Any]:
    return await _remote_bridge_request(
        "PUT",
        "config",
        payload={
            "client_key": next_client_key,
            "client_secret": next_client_secret,
            "miniapp_app_id": next_miniapp_app_id,
            "miniapp_secret": next_miniapp_secret,
        },
    )


async def remote_create_oauth_url(*, team_id: int, user_id: int) -> dict[str, Any]:
    return await _remote_bridge_request(
        "POST",
        "oauth/initiate",
        params={"team_id": int(team_id), "user_id": int(user_id)},
    )


async def remote_oauth_status(*, state: str, team_id: int) -> dict[str, Any]:
    return await _remote_bridge_request(
        "GET",
        "oauth/status",
        params={"state": state, "team_id": int(team_id)},
    )


async def remote_connection_status(team_id: int) -> dict[str, Any]:
    return await _remote_bridge_request(
        "GET",
        "connection",
        params={"team_id": int(team_id)},
    )


async def remote_send_message(
    *,
    team_id: int,
    contact_id: str,
    content: str,
    persona_id: str = "",
    customer_id: int = 0,
    reply_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _remote_bridge_request(
        "POST",
        "messages/send",
        payload={
            "team_id": int(team_id),
            "contact_id": contact_id,
            "content": content,
            "persona_id": persona_id,
            "customer_id": int(customer_id or 0),
            "reply_context": dict(reply_context or {}),
        },
    )


async def remote_pull_inbox(team_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    data = await _remote_bridge_request(
        "GET",
        "inbox",
        params={"team_id": int(team_id), "limit": max(1, min(int(limit), 200))},
    )
    rows = data.get("messages")
    return [dict(row) for row in rows] if isinstance(rows, list) else []


async def remote_ack_inbox(team_id: int, message_ids: list[str]) -> int:
    clean_ids = list(
        dict.fromkeys(
            str(message_id or "").strip()
            for message_id in message_ids
            if str(message_id or "").strip()
        )
    )[:200]
    if not clean_ids:
        return 0
    data = await _remote_bridge_request(
        "POST",
        "inbox/ack",
        payload={
            "team_id": int(team_id),
            "message_ids": clean_ids,
        },
    )
    return int(data.get("consumed") or 0)


def _require_ready() -> None:
    state = readiness()
    if state["missing"]:
        raise DouyinChannelError("抖音开放平台配置未完成：" + ", ".join(state["missing"]))
    if not state["public_https"]:
        raise DouyinChannelError("KELLAI_PUBLIC_BASE_URL 必须是公网 HTTPS 地址")


def _fernet() -> Fernet:
    seed = (
        _env("KELLAI_DOUYIN_STORAGE_KEY")
        or _env("KELLAI_DOUYIN_BRIDGE_KEY")
        or _env("KELLAI_WECOM_BRIDGE_KEY")
        or _channel_field("client_secret")
        or _channel_field("app_secret")
        or _env("KELLAI_DOUYIN_CLIENT_SECRET")
        or _env("KELLAI_DOUYIN_APP_SECRET")
    )
    if not seed:
        raise DouyinChannelError("缺少 KELLAI_DOUYIN_STORAGE_KEY 或抖音 Client Secret")
    key = base64.urlsafe_b64encode(hashlib.sha256(seed.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise DouyinChannelError("抖音授权密文无法解密，请检查存储密钥是否变化") from exc


def ensure_schema() -> None:
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kellai_douyin_oauth_sessions (
                state TEXT PRIMARY KEY,
                team_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT NOT NULL DEFAULT '',
                expires_at INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_douyin_oauth_team
                ON kellai_douyin_oauth_sessions(team_id, created_at);

            CREATE TABLE IF NOT EXISTS kellai_douyin_app_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                client_key TEXT NOT NULL DEFAULT '',
                client_secret_enc TEXT NOT NULL DEFAULT '',
                miniapp_app_id TEXT NOT NULL DEFAULT '',
                miniapp_secret_enc TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS kellai_douyin_authorizations (
                team_id INTEGER PRIMARY KEY,
                client_key TEXT NOT NULL,
                open_id TEXT NOT NULL UNIQUE,
                nickname TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT '',
                access_token_enc TEXT NOT NULL,
                refresh_token_enc TEXT NOT NULL,
                access_token_expires_at INTEGER NOT NULL DEFAULT 0,
                refresh_token_expires_at INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_douyin_auth_open_id
                ON kellai_douyin_authorizations(open_id);

            CREATE TABLE IF NOT EXISTS kellai_douyin_business_tokens (
                team_id INTEGER NOT NULL,
                open_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                token_enc TEXT NOT NULL,
                refresh_token_enc TEXT NOT NULL DEFAULT '',
                token_expires_at INTEGER NOT NULL DEFAULT 0,
                refresh_expires_at INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (team_id, open_id, scope)
            );
            """
        )
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(kellai_douyin_app_config)").fetchall()
        }
        if "miniapp_app_id" not in columns:
            conn.execute(
                "ALTER TABLE kellai_douyin_app_config "
                "ADD COLUMN miniapp_app_id TEXT NOT NULL DEFAULT ''"
            )
        if "miniapp_secret_enc" not in columns:
            conn.execute(
                "ALTER TABLE kellai_douyin_app_config "
                "ADD COLUMN miniapp_secret_enc TEXT NOT NULL DEFAULT ''"
            )
        conn.commit()


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    ensure_schema()
    conn = sqlite3.connect(str(_crm_db_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _stored_app_config() -> dict[str, str]:
    ensure_schema()
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT client_key, client_secret_enc, miniapp_app_id, miniapp_secret_enc
            FROM kellai_douyin_app_config
            WHERE id = 1
            """
        ).fetchone()
    if row is None:
        return {}
    return {
        "client_key": str(row["client_key"] or ""),
        "client_secret": _decrypt(str(row["client_secret_enc"] or "")),
        "miniapp_app_id": str(row["miniapp_app_id"] or ""),
        "miniapp_secret": _decrypt(str(row["miniapp_secret_enc"] or "")),
    }


def save_app_config(
    *,
    next_client_key: str,
    next_client_secret: str,
    next_miniapp_app_id: str = "",
    next_miniapp_secret: str = "",
) -> dict[str, Any]:
    current = _stored_app_config()
    clean_key = str(next_client_key or current.get("client_key") or "").strip()
    clean_secret = str(next_client_secret or current.get("client_secret") or "").strip()
    clean_miniapp_id = str(
        next_miniapp_app_id or current.get("miniapp_app_id") or ""
    ).strip()
    clean_miniapp_secret = str(
        next_miniapp_secret or current.get("miniapp_secret") or ""
    ).strip()
    if not clean_key or not clean_secret:
        raise DouyinChannelError("Client Key / Client Secret 不能为空")
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO kellai_douyin_app_config
                (id, client_key, client_secret_enc, miniapp_app_id,
                 miniapp_secret_enc, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                client_key = excluded.client_key,
                client_secret_enc = excluded.client_secret_enc,
                miniapp_app_id = excluded.miniapp_app_id,
                miniapp_secret_enc = excluded.miniapp_secret_enc,
                updated_at = excluded.updated_at
            """,
            (
                clean_key,
                _encrypt(clean_secret),
                clean_miniapp_id,
                _encrypt(clean_miniapp_secret),
                _now_iso(),
            ),
        )
    state = readiness()
    return {
        "configured": state["configured"],
        "client_key": clean_key,
        "secret_configured": True,
        "miniapp_app_id": clean_miniapp_id,
        "miniapp_secret_configured": bool(clean_miniapp_secret),
        "callback_url": state["callback_url"],
        "webhook_url": state["webhook_url"],
        "scopes": state["scopes"],
    }


async def validate_app_credentials(
    *,
    next_client_key: str = "",
    next_client_secret: str = "",
) -> dict[str, Any]:
    """向抖音开放平台换取 client_token，确认应用凭据真实可用。"""
    current = _stored_app_config()
    candidate_key = str(next_client_key or client_key() or current.get("client_key") or "").strip()
    candidate_secret = str(
        next_client_secret or client_secret() or current.get("client_secret") or ""
    ).strip()
    if not candidate_key or not candidate_secret:
        raise DouyinChannelError("Client Key / Client Secret 不能为空")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{DOUYIN_API_BASE}/oauth/client_token/",
                json={
                    "client_key": candidate_key,
                    "client_secret": candidate_secret,
                    "grant_type": "client_credential",
                },
            )
    except httpx.HTTPError as exc:
        raise DouyinChannelError("暂时无法连接抖音开放平台校验应用凭据") from exc
    try:
        body = response.json()
    except Exception as exc:
        raise DouyinChannelError(
            f"抖音应用凭据校验返回非 JSON：HTTP {response.status_code}"
        ) from exc
    data = body.get("data", {}) if isinstance(body, dict) else {}
    error_code = int(data.get("error_code", 0) or 0)
    token = str(data.get("access_token") or "")
    if response.status_code >= 400 or error_code != 0 or not token:
        message = str(
            data.get("description")
            or body.get("message")
            or f"error_code={error_code}"
        )
        raise DouyinChannelError(f"Client Key / Client Secret 校验失败：{message}")
    return {
        "credentials_valid": True,
        "client_key": candidate_key,
        "expires_in": int(data.get("expires_in", 0) or 0),
    }


async def save_app_config_verified(
    *,
    next_client_key: str,
    next_client_secret: str,
    next_miniapp_app_id: str = "",
    next_miniapp_secret: str = "",
) -> dict[str, Any]:
    current = _stored_app_config()
    candidate_key = str(next_client_key or current.get("client_key") or "").strip()
    candidate_secret = str(next_client_secret or current.get("client_secret") or "").strip()
    await validate_app_credentials(
        next_client_key=candidate_key,
        next_client_secret=candidate_secret,
    )
    result = save_app_config(
        next_client_key=candidate_key,
        next_client_secret=candidate_secret,
        next_miniapp_app_id=next_miniapp_app_id,
        next_miniapp_secret=next_miniapp_secret,
    )
    result["credentials_valid"] = True
    return result


def create_oauth_url(*, team_id: int, user_id: int) -> dict[str, Any]:
    _require_ready()
    if int(team_id) <= 0 or int(user_id) <= 0:
        raise DouyinChannelError("当前客来来账号没有有效团队或用户")

    state = secrets.token_urlsafe(32)
    now = int(time.time())
    expires_at = now + DOUYIN_OAUTH_TTL_SECONDS
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO kellai_douyin_oauth_sessions
                (state, team_id, user_id, status, error, expires_at, created_at, completed_at)
            VALUES (?, ?, ?, 'pending', '', ?, ?, '')
            """,
            (state, int(team_id), int(user_id), expires_at, _now_iso()),
        )

    params = {
        "client_key": client_key(),
        "response_type": "code",
        "scope": oauth_scopes(),
        "redirect_uri": callback_url(),
        "state": state,
    }
    url = f"{DOUYIN_AUTHORIZE_URL}?{urlencode(params)}"
    return {
        "url": url,
        "qr_text": url,
        "state": state,
        "expires_in": DOUYIN_OAUTH_TTL_SECONDS,
        "callback_url": callback_url(),
        "webhook_url": webhook_url(),
        "scopes": oauth_scopes().split(","),
    }


def _oauth_session(state: str) -> sqlite3.Row:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM kellai_douyin_oauth_sessions WHERE state = ?",
            (state,),
        ).fetchone()
    if row is None:
        raise DouyinChannelError("抖音授权 state 无效，请重新发起授权")
    return row


def fail_oauth(state: str, error: str) -> None:
    if not state:
        return
    with _conn() as conn:
        conn.execute(
            """
            UPDATE kellai_douyin_oauth_sessions
            SET status = 'failed', error = ?, completed_at = ?
            WHERE state = ?
            """,
            ((error or "抖音授权失败")[:500], _now_iso(), state),
        )


async def _fetch_user_info(access_token: str, open_id: str) -> dict[str, str]:
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(
                f"{DOUYIN_API_BASE}/oauth/userinfo/",
                params={"access_token": access_token, "open_id": open_id},
            )
        body = response.json()
        data = body.get("data", {}) if isinstance(body, dict) else {}
        error_code = int(data.get("error_code", body.get("err_no", 0)) or 0)
        if response.status_code >= 400 or error_code != 0:
            return {}
        return {
            "nickname": str(data.get("nickname") or ""),
            "avatar": str(data.get("avatar") or ""),
        }
    except Exception:
        return {}


async def complete_oauth(*, state: str, code: str) -> dict[str, Any]:
    _require_ready()
    session = _oauth_session(state)
    now = int(time.time())
    if str(session["status"]) == "authorized":
        auth = get_authorization(int(session["team_id"]), include_tokens=False)
        return auth or {"authorized": True}
    if now > int(session["expires_at"]):
        fail_oauth(state, "抖音授权二维码已过期")
        raise DouyinChannelError("抖音授权二维码已过期，请重新发起授权")
    if not code:
        fail_oauth(state, "抖音未返回授权码")
        raise DouyinChannelError("抖音未返回授权码")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{DOUYIN_API_BASE}/oauth/access_token/",
            data={
                "client_key": client_key(),
                "client_secret": client_secret(),
                "code": code,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    try:
        body = response.json()
    except Exception as exc:
        fail_oauth(state, f"抖音返回非 JSON：HTTP {response.status_code}")
        raise DouyinChannelError(f"抖音返回非 JSON：HTTP {response.status_code}") from exc

    data = body.get("data", {}) if isinstance(body, dict) else {}
    error_code = int(data.get("error_code", 0) or 0)
    if response.status_code >= 400 or error_code != 0:
        message = str(data.get("description") or body.get("message") or f"error_code={error_code}")
        fail_oauth(state, message)
        raise DouyinChannelError(f"抖音授权失败：{message}")

    access_token = str(data.get("access_token") or "")
    refresh_token = str(data.get("refresh_token") or "")
    open_id = str(data.get("open_id") or "")
    scope = str(data.get("scope") or "")
    if not access_token or not refresh_token or not open_id:
        fail_oauth(state, "抖音授权响应缺少 access_token/refresh_token/open_id")
        raise DouyinChannelError("抖音授权响应不完整")

    user_info = await _fetch_user_info(access_token, open_id)
    access_expires_at = now + int(data.get("expires_in", 1296000) or 1296000)
    refresh_expires_at = now + int(data.get("refresh_expires_in", 2592000) or 2592000)
    team_id = int(session["team_id"])
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO kellai_douyin_authorizations
                (team_id, client_key, open_id, nickname, avatar, scope,
                 access_token_enc, refresh_token_enc, access_token_expires_at,
                 refresh_token_expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(team_id) DO UPDATE SET
                client_key = excluded.client_key,
                open_id = excluded.open_id,
                nickname = excluded.nickname,
                avatar = excluded.avatar,
                scope = excluded.scope,
                access_token_enc = excluded.access_token_enc,
                refresh_token_enc = excluded.refresh_token_enc,
                access_token_expires_at = excluded.access_token_expires_at,
                refresh_token_expires_at = excluded.refresh_token_expires_at,
                updated_at = excluded.updated_at
            """,
            (
                team_id,
                client_key(),
                open_id,
                user_info.get("nickname", ""),
                user_info.get("avatar", ""),
                scope,
                _encrypt(access_token),
                _encrypt(refresh_token),
                access_expires_at,
                refresh_expires_at,
                _now_iso(),
            ),
        )
        conn.execute(
            """
            UPDATE kellai_douyin_oauth_sessions
            SET status = 'authorized', error = '', completed_at = ?
            WHERE state = ?
            """,
            (_now_iso(), state),
        )

    from app.channels.config_store import save as save_channel_config

    save_channel_config(
        "douyin",
        {
            "oauth_authorized": "true",
            "oauth_open_id": open_id,
            "oauth_scope": scope,
            "oauth_account_name": user_info.get("nickname", ""),
        },
        name="抖音",
        enabled=True,
        connected=True,
    )
    return {
        "authorized": True,
        "team_id": team_id,
        "open_id": open_id,
        "nickname": user_info.get("nickname", ""),
        "avatar": user_info.get("avatar", ""),
        "scope": scope,
    }


def get_oauth_status(*, state: str, team_id: int) -> dict[str, Any]:
    session = _oauth_session(state)
    if int(session["team_id"]) != int(team_id):
        raise DouyinChannelError("该抖音授权任务不属于当前团队")
    status = str(session["status"])
    expired = int(time.time()) > int(session["expires_at"]) and status == "pending"
    if expired:
        fail_oauth(state, "抖音授权二维码已过期")
        status = "failed"
    data: dict[str, Any] = {
        "authorized": status == "authorized",
        "expired": expired,
        "status": status,
        "error": str(session["error"] or ""),
    }
    if status == "authorized":
        auth = get_authorization(int(team_id), include_tokens=False) or {}
        data.update(
            {
                "open_id": auth.get("open_id", ""),
                "nickname": auth.get("nickname", ""),
                "scope": auth.get("scope", ""),
            }
        )
    return data


def get_authorization(team_id: int, *, include_tokens: bool = True) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM kellai_douyin_authorizations WHERE team_id = ?",
            (int(team_id),),
        ).fetchone()
    if row is None:
        return None
    result: dict[str, Any] = {
        "team_id": int(row["team_id"]),
        "client_key": str(row["client_key"]),
        "open_id": str(row["open_id"]),
        "nickname": str(row["nickname"]),
        "avatar": str(row["avatar"]),
        "scope": str(row["scope"]),
        "access_token_expires_at": int(row["access_token_expires_at"]),
        "refresh_token_expires_at": int(row["refresh_token_expires_at"]),
        "updated_at": str(row["updated_at"]),
    }
    if include_tokens:
        result["access_token"] = _decrypt(str(row["access_token_enc"]))
        result["refresh_token"] = _decrypt(str(row["refresh_token_enc"]))
    return result


def find_authorization_for_event(*open_ids: str) -> dict[str, Any] | None:
    candidates = [str(value or "").strip() for value in open_ids if str(value or "").strip()]
    if not candidates:
        return None
    placeholders = ",".join("?" for _ in candidates)
    with _conn() as conn:
        row = conn.execute(
            f"SELECT * FROM kellai_douyin_authorizations WHERE open_id IN ({placeholders}) LIMIT 1",
            candidates,
        ).fetchone()
    if row is None:
        return None
    return {
        "team_id": int(row["team_id"]),
        "client_key": str(row["client_key"]),
        "open_id": str(row["open_id"]),
        "nickname": str(row["nickname"]),
        "scope": str(row["scope"]),
    }


def default_team_for_miniapp_event(app_id: str = "") -> int | None:
    """Resolve mini-app IM callbacks to the existing Douyin team binding.

    Mini-app customer-service callbacks identify the customer with c_open_id, which
    is not the same namespace as the website/mobile OAuth open_id stored in
    kellai_douyin_authorizations.  Until the platform sends an OAuth open_id that
    can be matched directly, route the mini-app callback to an explicitly
    configured team or to the single existing Douyin team.
    """
    incoming_app_id = str(app_id or "").strip()
    configured_app_id = miniapp_app_id()
    if configured_app_id and incoming_app_id and incoming_app_id != configured_app_id:
        return None

    configured_team = _env("KELLAI_DOUYIN_DEFAULT_TEAM_ID")
    if configured_team:
        try:
            team_id = int(configured_team)
        except ValueError:
            team_id = 0
        if team_id > 0:
            return team_id

    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT team_id
            FROM kellai_douyin_authorizations
            ORDER BY team_id
            """
        ).fetchall()
    if len(rows) == 1:
        return int(rows[0]["team_id"])
    return None


async def business_token_context(
    *,
    team_id: int,
    owner_open_id: str,
    scope: str = "im.direct_message",
) -> dict[str, Any]:
    """Return a cached mini-app BusinessToken for an authorized operator.

    The private-message OpenAPI is a mini-app business capability. It does not
    accept the website/mobile OAuth access_token used by the legacy enterprise
    IM endpoint. The signing secret here is the Webhook AppSecret shown on the
    mini-app Webhooks page, as required by Douyin's BusinessToken API.
    """
    app_id = miniapp_app_id()
    webhook_secret = miniapp_secret()
    clean_owner = str(owner_open_id or "").strip()
    clean_scope = str(scope or "im.direct_message").strip()
    if not app_id:
        raise DouyinChannelError("缺少抖音小程序 AppID")
    if not webhook_secret:
        raise DouyinChannelError(
            "缺少抖音小程序 Webhook AppSecret；请在抖音开放平台“开发配置 → Webhooks”中复制"
        )
    if not clean_owner:
        raise DouyinChannelError("当前私信缺少经营抖音号 open_id，无法生成 BusinessToken")

    now = int(time.time())
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT token_enc, refresh_token_enc, token_expires_at, refresh_expires_at
            FROM kellai_douyin_business_tokens
            WHERE team_id = ? AND open_id = ? AND scope = ?
            """,
            (int(team_id), clean_owner, clean_scope),
        ).fetchone()
    if row is not None and now < int(row["token_expires_at"] or 0) - 300:
        return {
            "business_token": _decrypt(str(row["token_enc"] or "")),
            "business_refresh_token": _decrypt(str(row["refresh_token_enc"] or "")),
            "expires_at": int(row["token_expires_at"] or 0),
            "refresh_expires_at": int(row["refresh_expires_at"] or 0),
            "open_id": clean_owner,
            "app_id": app_id,
            "scope": clean_scope,
        }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{DOUYIN_API_BASE}/oauth/business_token/",
                json={
                    "client_key": app_id,
                    "client_secret": webhook_secret,
                    "open_id": clean_owner,
                    "scope": clean_scope,
                },
            )
    except httpx.HTTPError as exc:
        raise DouyinChannelError("暂时无法连接抖音开放平台生成 BusinessToken") from exc
    try:
        body = response.json()
    except Exception as exc:
        raise DouyinChannelError(
            f"抖音 BusinessToken 返回非 JSON：HTTP {response.status_code}"
        ) from exc

    data = body.get("data") if isinstance(body, dict) else None
    token_data = data if isinstance(data, dict) else body if isinstance(body, dict) else {}
    token = str(token_data.get("biz_token") or token_data.get("business_token") or "")
    refresh_token = str(
        token_data.get("biz_refresh_token")
        or token_data.get("business_refresh_token")
        or ""
    )
    error_code = int(
        token_data.get("error_code")
        or token_data.get("err_no")
        or body.get("error_code", 0)
        or body.get("err_no", 0)
        or 0
    )
    if response.status_code >= 400 or error_code != 0 or not token:
        description = str(
            token_data.get("description")
            or token_data.get("message")
            or body.get("message")
            or body.get("err_msg")
            or f"error_code={error_code}"
        )
        raise DouyinChannelError(f"抖音 BusinessToken 生成失败：{description}")

    expires_at = now + int(
        token_data.get("biz_expires_in")
        or token_data.get("expires_in")
        or 2592000
    )
    refresh_expires_at = now + int(
        token_data.get("biz_refresh_expires_in")
        or token_data.get("refresh_expires_in")
        or 31536000
    )
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO kellai_douyin_business_tokens
                (team_id, open_id, scope, token_enc, refresh_token_enc,
                 token_expires_at, refresh_expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(team_id, open_id, scope) DO UPDATE SET
                token_enc = excluded.token_enc,
                refresh_token_enc = excluded.refresh_token_enc,
                token_expires_at = excluded.token_expires_at,
                refresh_expires_at = excluded.refresh_expires_at,
                updated_at = excluded.updated_at
            """,
            (
                int(team_id),
                clean_owner,
                clean_scope,
                _encrypt(token),
                _encrypt(refresh_token),
                expires_at,
                refresh_expires_at,
                _now_iso(),
            ),
        )
    return {
        "business_token": token,
        "business_refresh_token": refresh_token,
        "expires_at": expires_at,
        "refresh_expires_at": refresh_expires_at,
        "open_id": clean_owner,
        "app_id": app_id,
        "scope": clean_scope,
    }


async def access_context(team_id: int) -> dict[str, Any]:
    auth = get_authorization(int(team_id), include_tokens=True)
    if auth is None:
        raise DouyinChannelError("当前团队尚未扫码授权抖音企业号")
    now = int(time.time())
    if now < int(auth["access_token_expires_at"]) - 120:
        return auth
    if now >= int(auth["refresh_token_expires_at"]) - 60:
        raise DouyinChannelError("抖音授权已过期，请重新扫码授权")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{DOUYIN_API_BASE}/oauth/refresh_token/",
            data={
                "client_key": client_key(),
                "grant_type": "refresh_token",
                "refresh_token": auth["refresh_token"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    try:
        body = response.json()
    except Exception as exc:
        raise DouyinChannelError(f"抖音刷新令牌返回非 JSON：HTTP {response.status_code}") from exc
    data = body.get("data", {}) if isinstance(body, dict) else {}
    error_code = int(data.get("error_code", 0) or 0)
    if response.status_code >= 400 or error_code != 0:
        message = str(data.get("description") or body.get("message") or f"error_code={error_code}")
        raise DouyinChannelError(f"抖音刷新令牌失败：{message}")

    next_access = str(data.get("access_token") or "")
    if not next_access:
        raise DouyinChannelError("抖音刷新令牌响应缺少 access_token")
    next_refresh = str(data.get("refresh_token") or auth["refresh_token"])
    access_expires_at = now + int(data.get("expires_in", 1296000) or 1296000)
    refresh_expires_at = int(auth["refresh_token_expires_at"])
    if data.get("refresh_expires_in"):
        refresh_expires_at = now + int(data["refresh_expires_in"])
    with _conn() as conn:
        conn.execute(
            """
            UPDATE kellai_douyin_authorizations
            SET access_token_enc = ?, refresh_token_enc = ?,
                access_token_expires_at = ?, refresh_token_expires_at = ?,
                scope = ?, updated_at = ?
            WHERE team_id = ?
            """,
            (
                _encrypt(next_access),
                _encrypt(next_refresh),
                access_expires_at,
                refresh_expires_at,
                str(data.get("scope") or auth["scope"]),
                _now_iso(),
                int(team_id),
            ),
        )
    return get_authorization(int(team_id), include_tokens=True) or auth


def _miniapp_live_verified(team_id: int) -> bool:
    """Whether at least one real mini-app IM event has reached the public inbox."""
    from app.services.message_store import ensure_messages_schema

    ensure_messages_schema()
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        rows = conn.execute(
            """
            SELECT metadata_json
            FROM kellai_channel_inbox
            WHERE channel_type = 'douyin'
            ORDER BY received_at DESC
            LIMIT 500
            """
        ).fetchall()
    expected_app_id = miniapp_app_id()
    for row in rows:
        try:
            metadata = json.loads(str(row[0] or "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(metadata, dict):
            continue
        if int(metadata.get("team_id") or 0) != int(team_id):
            continue
        if expected_app_id and str(metadata.get("miniapp_app_id") or "") != expected_app_id:
            continue
        if str(metadata.get("event") or "") in {
            "im_receive_msg",
            "im_send_msg",
            "im_enter_direct_msg",
            "im_authorize",
        }:
            return True
    return False


async def connection_status(team_id: int) -> dict[str, Any]:
    state = readiness()
    if not state["configured"]:
        return {
            "connected": False,
            "message": "抖音开放平台配置未完成：" + ", ".join(state["missing"]),
            "authorization": None,
        }
    try:
        await validate_app_credentials()
    except DouyinChannelError as exc:
        return {
            "connected": False,
            "credentials_valid": False,
            "message": str(exc),
            "authorization": None,
        }
    auth = get_authorization(int(team_id), include_tokens=False)
    if auth is None:
        return {
            "connected": False,
            "message": "当前团队尚未扫码授权抖音企业号",
            "authorization": None,
        }
    miniapp_state = state.get("miniapp") if isinstance(state.get("miniapp"), dict) else {}
    if miniapp_state.get("app_id_configured"):
        if not miniapp_state.get("webhook_secret_configured"):
            return {
                "connected": False,
                "credentials_valid": True,
                "message": "网站应用基础授权已完成；还缺少小程序 Webhook AppSecret，私信回复暂不可用",
                "authorization": auth,
                "miniapp": miniapp_state,
                "capabilities": {
                    "direct_message": False,
                    "miniapp_direct_message": False,
                    "group_message": False,
                },
            }
        live_verified = _miniapp_live_verified(int(team_id))
        return {
            "connected": True,
            "credentials_valid": True,
            "live_verified": live_verified,
            "mode": "miniapp_business_im",
            "message": (
                "抖音小程序私信已接通，真实消息已进入客来来"
                if live_verified
                else "抖音小程序私信配置完成，等待首条真实私信完成最终验证"
            ),
            "authorization": auth,
            "miniapp": miniapp_state,
            "capabilities": {
                "direct_message": True,
                "miniapp_direct_message": True,
                "group_message": False,
            },
        }
    scopes = {item.strip() for item in str(auth.get("scope") or "").split(",") if item.strip()}
    if "im.direct_message" not in scopes:
        return {
            "connected": False,
            "credentials_valid": True,
            "message": "抖音账号已完成基础授权；开放平台尚未授予 im.direct_message 私信权限，私信收发暂不可用",
            "authorization": auth,
            "capabilities": {
                "direct_message": False,
                "group_message": "im.group_fans.create_list" in scopes,
            },
        }
    await access_context(int(team_id))
    return {
        "connected": True,
        "message": f"抖音企业号已授权：{auth.get('nickname') or auth.get('open_id')}",
        "authorization": auth,
        "capabilities": {
            "direct_message": "im.direct_message" in scopes,
            "group_message": "im.group_fans.create_list" in scopes,
        },
    }


def _inbox_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except (json.JSONDecodeError, TypeError):
        metadata = {}
    return {
        "id": str(row["id"]),
        "channel_type": str(row["channel_type"]),
        "contact_id": str(row["contact_id"]),
        "contact_name": str(row["contact_name"]),
        "direction": str(row["direction"]),
        "content": str(row["content"]),
        "content_type": str(row["content_type"]),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "received_at": str(row["received_at"]),
        "consumed": int(row["consumed"] or 0),
    }


def pull_team_inbox(team_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    """读取当前团队的未消费消息；读取本身不改变消费状态。"""
    from app.services.message_store import ensure_messages_schema

    ensure_messages_schema()
    max_items = max(1, min(int(limit), 200))
    selected: list[dict[str, Any]] = []
    offset = 0
    batch_size = 500
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        while len(selected) < max_items:
            rows = conn.execute(
                """
                SELECT *
                FROM kellai_channel_inbox
                WHERE channel_type = 'douyin' AND consumed = 0
                ORDER BY received_at ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                (batch_size, offset),
            ).fetchall()
            if not rows:
                break
            for raw_row in rows:
                row = _inbox_row(raw_row)
                metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                if int(metadata.get("team_id") or 0) != int(team_id):
                    continue
                selected.append(row)
                if len(selected) >= max_items:
                    break
            offset += len(rows)
    return selected


def ack_team_inbox(team_id: int, message_ids: list[str]) -> int:
    """只确认属于指定团队且已经成功落到桌面端的消息。"""
    from app.services.message_store import ensure_messages_schema

    clean_ids = list(
        dict.fromkeys(
            str(message_id or "").strip()
            for message_id in message_ids
            if str(message_id or "").strip()
        )
    )[:200]
    if not clean_ids:
        return 0
    ensure_messages_schema()
    placeholders = ",".join("?" for _ in clean_ids)
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT id, metadata_json
            FROM kellai_channel_inbox
            WHERE channel_type = 'douyin' AND consumed = 0
              AND id IN ({placeholders})
            """,
            clean_ids,
        ).fetchall()
        owned_ids: list[str] = []
        for row in rows:
            try:
                metadata = json.loads(str(row["metadata_json"] or "{}"))
            except (json.JSONDecodeError, TypeError):
                metadata = {}
            if isinstance(metadata, dict) and int(metadata.get("team_id") or 0) == int(team_id):
                owned_ids.append(str(row["id"]))
        if not owned_ids:
            return 0
        owned_placeholders = ",".join("?" for _ in owned_ids)
        cur = conn.execute(
            f"""
            UPDATE kellai_channel_inbox
            SET consumed = 1
            WHERE consumed = 0 AND id IN ({owned_placeholders})
            """,
            owned_ids,
        )
        conn.commit()
        return int(cur.rowcount or 0)


def revoke_authorization(*, team_id: int | None = None, open_id: str = "") -> bool:
    if team_id is None and not open_id:
        return False
    with _conn() as conn:
        if team_id is not None:
            cur = conn.execute(
                "DELETE FROM kellai_douyin_authorizations WHERE team_id = ?",
                (int(team_id),),
            )
        else:
            cur = conn.execute(
                "DELETE FROM kellai_douyin_authorizations WHERE open_id = ?",
                (str(open_id),),
            )
    return bool(cur.rowcount)


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    if not signature:
        return False
    provided = signature.strip().lower()
    signing_secrets = list(
        dict.fromkeys(
            value
            for value in (
                client_secret(),
                miniapp_secret(),
            )
            if value
        )
    )
    for secret in signing_secrets:
        expected = hashlib.sha1(secret.encode("utf-8") + raw_body).hexdigest()
        if secrets.compare_digest(expected, provided):
            return True
    return False


def parse_event_content(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
