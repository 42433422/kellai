"""Single local handoff and scoped tool grant for XCMAX."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from app.services.auth import create_operator_session, operator, workspace_id
from app.services.tenant_context import base_data_root

PROTOCOL_VERSION = 2
SCOPES = {"channels.read", "messages.read", "messages.send"}
_HANDOFFS: dict[tuple[str, str], dict] = {}
_LOCK = threading.RLock()


def _store_path() -> Path:
    return base_data_root() / "tenants" / str(workspace_id()) / "integrations" / "xcmax.json"


def _read() -> dict:
    path = _store_path()
    if not path.exists():
        return {"version": PROTOCOL_VERSION, "connection": None}
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("XCMAX 配对记录无效")
    connection = result.get("connection")
    if isinstance(connection, dict) and "access_token" in connection:
        # Migrate the verification material without keeping the old plaintext
        # token. Its v1 grant remains revoked until the user reauthorizes v2.
        raw = str(connection.pop("access_token") or "")
        connection["token_hash"] = hashlib.sha256(raw.encode()).hexdigest() if raw else ""
        connection["requires_reconnect"] = True
        _write(result)
    return result


def _write(value: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _xcmax_base() -> str:
    raw = (os.environ.get("KELLAI_XCMAX_API_BASE") or "http://127.0.0.1:17500").rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise RuntimeError("XCMAX 地址必须是本机回环地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise RuntimeError("XCMAX 地址不能包含凭据、路径或查询参数")
    return raw


def _xcmax_request(path: str, *, method: str = "GET", data: dict | None = None) -> dict:
    try:
        with httpx.Client(timeout=4, follow_redirects=False, trust_env=False) as client:
            response = client.request(method, _xcmax_base() + path, json=data, headers={
                "X-Kellai-Local-Pairing": "1", "X-XCMAX-Client-Shell": "enterprise",
                "Accept": "application/json",
            })
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("无法完成 XCMAX 本机交接，请确认宿主正在运行并重新发起连接") from exc
    if not isinstance(body, dict) or body.get("success") is not True:
        raise RuntimeError("XCMAX 未接受此操作")
    return body


def _handoff_key(request_id: str) -> tuple[str, str]:
    return str(base_data_root()), request_id


def _pending_metadata(pending: dict | None) -> dict | None:
    if not isinstance(pending, dict):
        return None
    return {key: value for key, value in pending.items()
            if key not in {"authorization_secret", "access_token", "token_hash", "bootstrap_nonce"}}


def _public_connection(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {"connection_id": str(value.get("connection_id") or ""),
            "authorized_scopes": list(value.get("authorized_scopes") or []),
            "authorized_by": value.get("authorized_by") or {},
            "protocol_version": int(value.get("protocol_version") or 1),
            "requires_reconnect": value.get("protocol_version") != PROTOCOL_VERSION}


def public_status() -> dict:
    state = _read()
    local = state.get("connection")
    valid = (isinstance(local, dict) and local.get("protocol_version") == PROTOCOL_VERSION
             and not local.get("requires_reconnect"))
    # A local grant proves authorization, not host process liveness. The host's
    # session-authenticated status endpoint is deliberately not called here.
    return {"state": "connected" if valid else "not_connected", "connected": bool(valid),
            "connection": _public_connection(local), "pending": pending_authorization(),
            "available_scopes": sorted(SCOPES), "host_state": "not_checked",
            "host_cleanup_required": bool(state.get("host_cleanup_required")),
            "message": "本机授权已记录；宿主运行状态请在 XCMAX 查看" if valid else ""}


def create_desktop_login_for_pending_pairing() -> dict:
    # The host atomically consumes a handoff once. A status GET never proves
    # possession and cannot mint an operator session.
    data = _xcmax_request("/api/kellai/binding/handoff", method="POST", data={}).get("data")
    if not isinstance(data, dict):
        raise RuntimeError("未检测到有效的 XCMAX 交接")
    request_id = str(data.get("request_id") or "")
    secret = str(data.get("authorization_secret") or "")
    if not request_id or len(secret) < 32 or data.get("protocol_version") != PROTOCOL_VERSION:
        raise RuntimeError("XCMAX 交接响应缺少一次性授权凭据")
    with _LOCK:
        for key in list(_HANDOFFS):
            if key[0] == str(base_data_root()):
                del _HANDOFFS[key]
        _HANDOFFS[_handoff_key(request_id)] = {**data, "received_at": time.time(), "workspace_id": workspace_id()}
    return create_operator_session()


def _handoff_live(value: dict) -> bool:
    if int(value.get("workspace_id") or 0) != workspace_id():
        return False
    if time.time() - float(value.get("received_at") or 0) > 600:
        return False
    expiry = value.get("expires_at")
    if expiry:
        try:
            expires = (float(expiry) if isinstance(expiry, (int, float)) else
                       datetime.fromisoformat(str(expiry).replace("Z", "+00:00")).timestamp())
            if expires <= time.time():
                return False
        except (ValueError, TypeError, OverflowError):
            return False
    return True


def pending_authorization() -> dict | None:
    # Only the one-time claim carries proof; never ask an unauthenticated host
    # status endpoint for a pending secret or an operator session.
    with _LOCK:
        candidates = [value for key, value in _HANDOFFS.items()
                      if key[0] == str(base_data_root()) and _handoff_live(value)]
    return _pending_metadata(candidates[0]) if len(candidates) == 1 else None


def _handoff(request_id: str) -> dict:
    with _LOCK:
        value = _HANDOFFS.get(_handoff_key(request_id))
    if not value or not _handoff_live(value):
        raise RuntimeError("本机交接已失效，请从 XCMAX 重新打开账号工具")
    return value


def approve_authorization(*, request_id: str, accepted_scopes: list[str], current_user: dict) -> dict:
    if not accepted_scopes or not set(accepted_scopes).issubset(SCOPES):
        raise RuntimeError("授权范围无效")
    if int(current_user.get("team_id") or 0) != workspace_id() or current_user.get("role") != "owner":
        raise RuntimeError("工作区操作者身份无效")
    pending = _handoff(request_id)
    requested = {str(item.get("id") or "") for item in pending.get("requested_scopes", []) if isinstance(item, dict)}
    if not set(accepted_scopes).issubset(requested):
        raise RuntimeError("不能授予宿主本次未请求的权限")
    token = secrets.token_urlsafe(40)
    user = {"id": current_user["id"], "display_name": "本地操作者"}
    # Only activate the local grant after the host acknowledges the exact scope.
    # A failure before local persistence remains unavailable and requires re-pairing.
    response = _xcmax_request("/api/kellai/binding/approve", method="POST", data={
        "request_id": request_id, "authorization_secret": pending["authorization_secret"],
        "accepted_scopes": accepted_scopes, "access_token": token, "authorized_by": user,
        "protocol_version": PROTOCOL_VERSION,
    })
    with _LOCK:
        # The host roundtrip may overlap a local revoke or a new handoff.
        # Only the still-current, live claim can activate this exact grant.
        if (_HANDOFFS.get(_handoff_key(request_id)) is not pending
                or not _handoff_live(pending)):
            raise RuntimeError("本机交接已失效，请从 XCMAX 重新打开账号工具")
        _write({"version": PROTOCOL_VERSION, "connection": {
            "connection_id": request_id, "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "authorized_scopes": sorted(set(accepted_scopes)), "authorized_by": user,
            "team_id": workspace_id(), "protocol_version": PROTOCOL_VERSION,
        }})
        _HANDOFFS.pop(_handoff_key(request_id), None)
    return response.get("data") or {}


def cancel_authorization(*, request_id: str) -> None:
    pending = _handoff(request_id)
    _xcmax_request("/api/kellai/binding/cancel", method="POST", data={
        "request_id": request_id, "authorization_secret": pending["authorization_secret"],
    })
    with _LOCK:
        _HANDOFFS.pop(_handoff_key(request_id), None)


def disconnect() -> dict:
    # Local revocation is authoritative: the old host token immediately stops
    # working. The host's owner-only disconnect API requires its own user session.
    with _LOCK:
        _write({"version": PROTOCOL_VERSION, "connection": None, "host_cleanup_required": True})
        for key in list(_HANDOFFS):
            if key[0] == str(base_data_root()):
                del _HANDOFFS[key]
    return {"local_grant_revoked": True, "host_metadata_cleared": False, "host_cleanup_required": True}


def authorize_access_token(token: str, required_scope: str | None = None) -> dict:
    connection = _read().get("connection")
    if not isinstance(connection, dict):
        raise HTTPException(status_code=401, detail={"code": "xcmax_grant_revoked", "message": "XCMAX 本机授权已失效，请重新连接"})
    if connection.get("protocol_version") != PROTOCOL_VERSION or connection.get("requires_reconnect"):
        raise HTTPException(status_code=403, detail={"code": "xcmax_reauthorization_required", "message": "工具权限已收敛，请重新确认 XCMAX 授权"})
    expected = str(connection.get("token_hash") or "")
    if not token or not expected or not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected):
        raise HTTPException(status_code=401, detail={"code": "xcmax_grant_invalid", "message": "XCMAX 本机访问令牌无效"})
    if required_scope and required_scope not in set(connection.get("authorized_scopes") or []):
        raise HTTPException(status_code=403, detail={"code": "xcmax_scope_required", "message": "此工具操作未授权"})
    return {**connection, "team_id": workspace_id(), "actor": operator()}
