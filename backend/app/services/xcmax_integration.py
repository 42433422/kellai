"""Local XCMAX pairing client and read-only customer-data gateway."""

from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import HTTPException


_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _store_path() -> Path:
    from app.services.tenant_context import tenant_data_root

    root = tenant_data_root(required=False)
    path = root / "integrations" / "xcmax.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read() -> dict[str, Any]:
    path = _store_path()
    return _read_path(path)


def _read_path(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "connection": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "connection": None}
    return raw if isinstance(raw, dict) else {"version": 1, "connection": None}


def _write(value: dict[str, Any]) -> None:
    path = _store_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _xcmax_base() -> str:
    raw = (os.environ.get("KELLAI_XCMAX_API_BASE") or "http://127.0.0.1:17500").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _LOCAL_HOSTS:
        raise RuntimeError("XCMAX 桌面端地址必须是本机回环地址")
    return raw


def _xcmax_request(path: str, *, method: str = "GET", data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    request = urllib.request.Request(
        f"{_xcmax_base()}{path}",
        data=payload,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Kellai-Local-Pairing": "1",
            "X-XCMAX-Client-Shell": "enterprise",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:  # noqa: S310 - validated loopback URL
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            details = json.loads(exc.read().decode("utf-8"))
            message = details.get("detail") or details.get("error") or str(exc)
        except Exception:
            message = str(exc)
        raise RuntimeError(str(message)) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法连接 XCMAX 桌面端：{exc}") from exc
    if not isinstance(body, dict) or not body.get("success"):
        raise RuntimeError(str((body or {}).get("error") or "XCMAX 未接受此操作"))
    return body


def public_status() -> dict[str, Any]:
    local = _read().get("connection")
    try:
        remote = _xcmax_request("/api/kellai/binding/status").get("data") or {}
    except RuntimeError as exc:
        return {
            "state": "offline" if local else "not_connected",
            "connected": bool(local),
            "message": str(exc),
            "connection": _public_connection(local),
        }
    return {
        "state": str(remote.get("state") or "not_connected"),
        "connected": str(remote.get("state") or "") == "connected" and bool(local),
        "connection": remote.get("connection") or _public_connection(local),
        "pending": remote.get("pending"),
        "available_scopes": remote.get("available_scopes") or [],
        "message": "",
    }


def pending_authorization() -> dict[str, Any] | None:
    body = _xcmax_request("/api/kellai/binding/pending")
    data = body.get("data")
    return data if isinstance(data, dict) else None


def create_desktop_login_for_pending_pairing() -> dict[str, Any]:
    """Create or reuse the local desktop identity for an active XCMAX pairing.

    A pending request is the proof that XCMAX initiated this handoff on the
    same machine.  It only signs the user into 客来来 so they can review and
    confirm the authorization; data access is still unavailable until approve.
    """
    if not pending_authorization():
        raise RuntimeError("未检测到有效的 XCMAX 绑定请求")

    from app.services.auth import create_login_session_for_user, register_user

    state = _read()
    identity = state.get("desktop_identity")
    if isinstance(identity, dict):
        session = create_login_session_for_user(identity.get("user_id"))
        if session.get("success"):
            return session

    result = register_user(
        email=f"xcmax-{secrets.token_hex(16)}@desktop.local",
        password=f"{secrets.token_urlsafe(32)}Aa1!",
        display_name="XCMAX 桌面用户",
    )
    if not result.get("success") or not isinstance(result.get("user"), dict):
        raise RuntimeError(str(result.get("error") or "无法初始化客来来桌面身份"))

    user_id = result["user"].get("id")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("无法初始化客来来桌面身份") from exc

    state["desktop_identity"] = {"user_id": user_id}
    _write(state)
    return result


def approve_authorization(
    *,
    request_id: str,
    authorization_secret: str,
    accepted_scopes: list[str],
    current_user: dict[str, Any],
) -> dict[str, Any]:
    from app.services.tenant_context import current_team_id

    team_id = current_team_id()
    if team_id <= 0:
        raise RuntimeError("缺少已认证的租户上下文")
    token = secrets.token_urlsafe(40)
    user = {
        "id": current_user.get("id") or "",
        "display_name": current_user.get("display_name") or current_user.get("email") or current_user.get("phone") or "客来来用户",
    }
    body = _xcmax_request(
        "/api/kellai/binding/approve",
        method="POST",
        data={
            "request_id": request_id,
            "authorization_secret": authorization_secret,
            "accepted_scopes": accepted_scopes,
            "access_token": token,
            "authorized_by": user,
        },
    )
    state = _read()
    state["connection"] = {
        "connection_id": request_id,
        "access_token": token,
        "authorized_scopes": accepted_scopes,
        "authorized_by": user,
        "team_id": team_id,
    }
    _write(state)
    return body.get("data") if isinstance(body.get("data"), dict) else {}


def cancel_authorization(*, request_id: str, authorization_secret: str) -> None:
    _xcmax_request(
        "/api/kellai/binding/cancel",
        method="POST",
        data={"request_id": request_id, "authorization_secret": authorization_secret},
    )


def disconnect() -> None:
    try:
        _xcmax_request("/api/kellai/binding/disconnect", method="POST", data={})
    finally:
        state = _read()
        state["connection"] = None
        _write(state)


def _public_connection(connection: Any) -> dict[str, Any] | None:
    if not isinstance(connection, dict):
        return None
    return {
        "connection_id": str(connection.get("connection_id") or ""),
        "authorized_scopes": list(connection.get("authorized_scopes") or []),
        "authorized_by": connection.get("authorized_by") if isinstance(connection.get("authorized_by"), dict) else {},
    }


def authorize_access_token(token: str, required_scope: str) -> dict[str, Any]:
    from app.services.tenant_context import (
        base_data_root,
        current_team_id,
        infer_legacy_owner_team_id,
    )

    candidates: list[tuple[int, dict[str, Any]]] = []
    context_team_id = current_team_id()
    if context_team_id > 0:
        state = _read()
        connection = state.get("connection")
        if isinstance(connection, dict):
            candidates.append((context_team_id, connection))
    else:
        tenant_root = base_data_root() / "tenants"
        if tenant_root.is_dir():
            for path in tenant_root.glob("*/integrations/xcmax.json"):
                try:
                    team_id = int(path.parents[1].name)
                except (TypeError, ValueError):
                    continue
                connection = _read_path(path).get("connection")
                if isinstance(connection, dict):
                    candidates.append((team_id, connection))
        legacy_path = base_data_root() / "integrations" / "xcmax.json"
        legacy_connection = _read_path(legacy_path).get("connection")
        legacy_team_id = infer_legacy_owner_team_id()
        if isinstance(legacy_connection, dict) and legacy_team_id > 0:
            candidates.append((legacy_team_id, legacy_connection))

    connection: dict[str, Any] | None = None
    matched_team_id = 0
    for candidate_team_id, candidate in candidates:
        expected = str(candidate.get("access_token") or "")
        if token and expected and secrets.compare_digest(token, expected):
            connection = dict(candidate)
            matched_team_id = int(candidate_team_id)
            break
    if connection is None:
        raise HTTPException(status_code=401, detail="XCMAX 本地访问令牌无效")
    if required_scope not in set(connection.get("authorized_scopes") or []):
        raise HTTPException(status_code=403, detail="该数据权限未授权")
    connection["team_id"] = matched_team_id
    return connection
