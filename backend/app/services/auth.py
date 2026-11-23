"""Local operator sessions established by XCMAX's one-time desktop handoff.

There are no customer accounts, passwords, registration, teams or subscriptions
in the tool. The workspace number only preserves ownership of existing data.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time

from fastapi import HTTPException, Request

from app.services.storage import database_path
from app.services.tenant_context import legacy_owner_candidates

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
LOCAL_ORIGINS = {
    "tauri://localhost", "tauri://127.0.0.1", "http://tauri.localhost",
    "https://tauri.localhost", "http://127.0.0.1:1420", "http://localhost:1420",
    "http://127.0.0.1:5173", "http://localhost:5173",
}


def workspace_id() -> int:
    explicit = (os.environ.get("KELLAI_WORKSPACE_ID") or "").strip()
    if explicit:
        value = int(explicit)
        if value <= 0:
            raise RuntimeError("KELLAI_WORKSPACE_ID 必须为正整数")
        return value
    candidates = legacy_owner_candidates()
    if len(candidates) > 1:
        raise RuntimeError("历史数据包含多个工作区，请明确设置 KELLAI_WORKSPACE_ID；不会自动选择账号")
    return next(iter(candidates), 1)


def operator() -> dict:
    return {"id": 1, "team_id": workspace_id(), "role": "owner", "display_name": "本地操作者"}


def _sessions(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS kellai_tool_sessions (
        token_hash TEXT PRIMARY KEY, workspace_id INTEGER NOT NULL,
        expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL
    )""")


def create_operator_session() -> dict:
    token = secrets.token_urlsafe(40)
    now = int(time.time())
    expires_at = now + 24 * 60 * 60
    user = operator()
    with sqlite3.connect(str(database_path())) as conn:
        _sessions(conn)
        conn.execute("DELETE FROM kellai_tool_sessions WHERE expires_at<=?", (now,))
        conn.execute("INSERT INTO kellai_tool_sessions VALUES (?,?,?,?)", (
            hashlib.sha256(token.encode()).hexdigest(), user["team_id"], expires_at, now))
    return {"success": True, "access_token": token, "expires_at": expires_at, "user": user}


def verify_token(token: str) -> dict | None:
    if not token or len(token) > 512:
        return None
    with sqlite3.connect(str(database_path())) as conn:
        _sessions(conn)
        row = conn.execute("SELECT workspace_id,expires_at FROM kellai_tool_sessions WHERE token_hash=?",
                           (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if row is None or int(row[1]) <= int(time.time()) or int(row[0]) != workspace_id():
        return None
    return operator()


def revoke_session(token: str) -> None:
    with sqlite3.connect(str(database_path())) as conn:
        _sessions(conn)
        conn.execute("DELETE FROM kellai_tool_sessions WHERE token_hash=?",
                     (hashlib.sha256(token.encode()).hexdigest(),))


def require_local_request(request: Request, *, header: str | None = None) -> None:
    host = str(getattr(request.client, "host", ""))
    target = str(request.url.hostname or "")
    # testclient is only a synthetic ASGI peer, never a production TCP peer.
    if host not in LOCAL_HOSTS or target not in LOCAL_HOSTS | {"testserver"}:
        raise HTTPException(status_code=403, detail="此操作仅允许本机 XCMAX 交接")
    if header and request.headers.get(header) != "1":
        raise HTTPException(status_code=403, detail="缺少本机交接标识")
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in LOCAL_ORIGINS:
        raise HTTPException(status_code=403, detail="不允许此页面发起本机交接")
    if request.headers.get("sec-fetch-site") == "cross-site" and not origin:
        raise HTTPException(status_code=403, detail="不允许跨站本机交接")
