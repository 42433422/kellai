"""第三方抖音客服工作台连接器。

目标站点的前端公开调用 JSON API 与 WebSocket。客来来只保存用户主动提供的
网站 token，不读取浏览器存储，也不保存第三方账号密码。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from cryptography.fernet import Fernet

from app.channels.base import UnifiedMessage
from app.services.crm_store import _crm_db_path
from app.services.douyin_channel import _decrypt as _legacy_decrypt
from app.services.message_store import (
    ensure_messages_schema,
    mark_inbox_consumed,
    push_inbox,
    save_message,
)

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://dyylkapi.yidongwl.com/"

_MONITOR_TASKS: dict[int, asyncio.Task[None]] = {}
_MONITOR_LOCK = asyncio.Lock()


class DouyinWebPortalError(RuntimeError):
    """第三方客服工作台连接失败。"""


class DouyinWebPortalAuthError(DouyinWebPortalError):
    """第三方客服工作台 token 无效或过期。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_base() -> str:
    value = os.environ.get("KELLAI_DOUYIN_WEB_PORTAL_API_BASE", DEFAULT_API_BASE).strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise DouyinWebPortalError("抖音客服网页 API 地址必须是 HTTPS")
    return value.rstrip("/") + "/"


def _token_key_path():
    return _crm_db_path().parent / ".douyin-web-portal.key"


def _token_fernet() -> Fernet:
    """返回网站 Token 专用密钥，不依赖抖音开放平台 Client Secret。"""
    configured = os.environ.get("KELLAI_DOUYIN_WEB_PORTAL_STORAGE_KEY", "").strip()
    if configured:
        key = base64.urlsafe_b64encode(
            hashlib.sha256(configured.encode("utf-8")).digest()
        )
        return Fernet(key)

    key_path = _token_key_path()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        key = key_path.read_bytes().strip()
        return Fernet(key)

    generated = Fernet.generate_key()
    try:
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        key = key_path.read_bytes().strip()
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(generated)
        key = generated
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    return Fernet(key)


def _encrypt_token(value: str) -> str:
    if not value:
        return ""
    return _token_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_token(value: str) -> str:
    if not value:
        return ""
    try:
        return _token_fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except Exception:
        # 兼容此前使用抖音开放平台存储密钥加密的已有记录。
        try:
            return _legacy_decrypt(value)
        except Exception as exc:
            raise DouyinWebPortalAuthError(
                "网站 Token 无法解密，请重新输入当前登录会话的 Token"
            ) from exc


def extract_token(value: str) -> str:
    """接受纯 token，并兼容常见的复制粘贴格式。"""
    clean = str(value or "").strip().strip("\"'").strip()
    if not clean:
        return ""

    # 有些浏览器会复制 URL 编码后的完整地址。
    decoded = unquote(clean)
    if "://" in decoded and "://" not in clean:
        clean = decoded

    lowered = clean.lower()
    if lowered.startswith("bearer "):
        return clean[7:].strip().strip("\"'").strip()
    if lowered.startswith("token="):
        return unquote(clean.split("=", 1)[1]).strip().strip("\"'").strip()
    if lowered.startswith("token:"):
        return clean.split(":", 1)[1].strip().strip("\"'").strip()
    if "://" not in clean:
        return clean

    parsed = urlparse(clean)
    token = (parse_qs(parsed.query).get("token") or [""])[0].strip()
    if not token and parsed.fragment:
        fragment = parsed.fragment
        if "?" in fragment:
            fragment = fragment.split("?", 1)[1]
        token = (parse_qs(fragment).get("token") or [""])[0].strip()
    return token.strip("\"'").strip()


def ensure_schema() -> None:
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kellai_douyin_web_portal (
                team_id INTEGER PRIMARY KEY,
                token_enc TEXT NOT NULL DEFAULT '',
                account_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'disconnected',
                monitor_enabled INTEGER NOT NULL DEFAULT 0,
                last_sync_at TEXT NOT NULL DEFAULT '',
                last_message_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS kellai_douyin_web_contacts (
                team_id INTEGER NOT NULL,
                contact_id TEXT NOT NULL,
                account_id TEXT NOT NULL DEFAULT '',
                account_name TEXT NOT NULL DEFAULT '',
                conversation_id TEXT NOT NULL DEFAULT '',
                contact_name TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '',
                latest_content TEXT NOT NULL DEFAULT '',
                latest_message_type TEXT NOT NULL DEFAULT '',
                latest_message_at TEXT NOT NULL DEFAULT '',
                unread_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (team_id, contact_id)
            );
            CREATE INDEX IF NOT EXISTS idx_douyin_web_contacts_account
                ON kellai_douyin_web_contacts(team_id, account_id);
            """
        )
        conn.commit()


@contextmanager
def _conn():
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


def _stored_token(team_id: int) -> str:
    with _conn() as conn:
        row = conn.execute(
            "SELECT token_enc FROM kellai_douyin_web_portal WHERE team_id = ?",
            (int(team_id),),
        ).fetchone()
    return _decrypt_token(str(row["token_enc"] or "")) if row else ""


def _update_state(team_id: int, **values: Any) -> None:
    allowed = {
        "account_name",
        "status",
        "monitor_enabled",
        "last_sync_at",
        "last_message_at",
        "last_error",
    }
    clean = {key: value for key, value in values.items() if key in allowed}
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO kellai_douyin_web_portal
                (team_id, updated_at)
            VALUES (?, ?)
            ON CONFLICT(team_id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (int(team_id), _now_iso()),
        )
        if clean:
            assignments = ", ".join(f"{key} = ?" for key in clean)
            conn.execute(
                f"UPDATE kellai_douyin_web_portal SET {assignments}, updated_at = ? "
                "WHERE team_id = ?",
                [*clean.values(), _now_iso(), int(team_id)],
            )


async def _post(token: str, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
    if not token:
        raise DouyinWebPortalAuthError("尚未绑定抖音客服网页")
    async with httpx.AsyncClient(
        base_url=_api_base(),
        timeout=30.0,
        headers={
            "token": token,
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Kellai-Douyin-Web-Portal/1.0",
        },
    ) as client:
        response = await client.post(endpoint, json=payload or {})
    try:
        body = response.json()
    except Exception as exc:
        if response.status_code == 401:
            raise DouyinWebPortalAuthError(
                "网站 Token 无效或已过期，请重新复制当前登录会话的 Token"
            ) from exc
        raise DouyinWebPortalError(
            f"抖音客服网页返回非 JSON：HTTP {response.status_code}"
        ) from exc
    code = 0
    if isinstance(body, dict):
        try:
            code = int(body.get("code", 0) or 0)
        except (TypeError, ValueError):
            code = 0
    if response.status_code == 401 or code == 401:
        raise DouyinWebPortalAuthError(
            "网站 Token 无效或已过期，请重新复制当前登录会话的 Token"
        )
    if response.status_code >= 400:
        message = str(body.get("msg") or "").strip() if isinstance(body, dict) else ""
        suffix = f"：{message}" if message else ""
        raise DouyinWebPortalError(
            f"抖音客服网页请求失败：HTTP {response.status_code}{suffix}"
        )
    if code != 1:
        raise DouyinWebPortalError(str(body.get("msg") or f"接口返回 code={code}"))
    return body.get("data")


async def connect(team_id: int, token_or_url: str) -> dict[str, Any]:
    token = extract_token(token_or_url)
    if len(token) < 8:
        raise DouyinWebPortalAuthError("连接地址或 token 不完整")
    info = await _post(token, "service/service/index")
    account_name = ""
    if isinstance(info, dict):
        account_name = str(
            info.get("server_name")
            or info.get("member_name")
            or info.get("nickname")
            or ""
        ).strip()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO kellai_douyin_web_portal
                (team_id, token_enc, account_name, status, monitor_enabled,
                 last_error, updated_at)
            VALUES (?, ?, ?, 'connected', 0, '', ?)
            ON CONFLICT(team_id) DO UPDATE SET
                token_enc = excluded.token_enc,
                account_name = excluded.account_name,
                status = 'connected',
                last_error = '',
                updated_at = excluded.updated_at
            """,
            (int(team_id), _encrypt_token(token), account_name, _now_iso()),
        )
    return {
        "connected": True,
        "account_name": account_name,
        "token_saved": True,
    }


def disconnect(team_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM kellai_douyin_web_portal WHERE team_id = ?",
            (int(team_id),),
        )
        conn.execute(
            "DELETE FROM kellai_douyin_web_contacts WHERE team_id = ?",
            (int(team_id),),
        )
    return bool(cur.rowcount)


def status(team_id: int) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM kellai_douyin_web_portal WHERE team_id = ?",
            (int(team_id),),
        ).fetchone()
        contact_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM kellai_douyin_web_contacts WHERE team_id = ?",
                (int(team_id),),
            ).fetchone()[0]
        )
    task = _MONITOR_TASKS.get(int(team_id))
    monitor_running = bool(task and not task.done())
    if not row:
        return {
            "connected": False,
            "status": "disconnected",
            "monitor_running": False,
            "contact_count": 0,
        }
    return {
        "connected": bool(row["token_enc"]) and str(row["status"]) != "expired",
        "status": str(row["status"] or "disconnected"),
        "account_name": str(row["account_name"] or ""),
        "monitor_enabled": bool(row["monitor_enabled"]),
        "monitor_running": monitor_running,
        "last_sync_at": str(row["last_sync_at"] or ""),
        "last_message_at": str(row["last_message_at"] or ""),
        "last_error": str(row["last_error"] or ""),
        "contact_count": contact_count,
    }


def _message_content(message_type: str, content: Any, extend: Any = None) -> str:
    text = str(content or "").strip()
    if message_type == "text" and text:
        return text
    labels = {
        "emoji": "[表情]",
        "image": "[图片]",
        "user_local_image": "[图片]",
        "video": "[视频]",
        "user_local_video": "[视频]",
        "card": "[卡片]",
        "retain_consult_card": "[客户提交了留资卡]",
        "crowd_card": "[群聊邀请]",
        "groupchat": "[群聊消息]",
    }
    if text:
        return text
    if extend:
        return labels.get(message_type, f"[{message_type or '消息'}]")
    return labels.get(message_type, f"[{message_type or '消息'}]")


def _timestamp(value: Any) -> str:
    if value is None or value == "":
        return _now_iso()
    try:
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        return datetime.fromtimestamp(raw, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return str(value)


def _stable_message_id(team_id: int, contact_id: str, item: dict[str, Any]) -> str:
    remote_id = str(item.get("server_message_id") or item.get("msg_id") or item.get("id") or "")
    if remote_id:
        return f"douyin:web:{remote_id}"
    raw = "|".join(
        [
            str(team_id),
            contact_id,
            str(item.get("from_open_id") or ""),
            str(item.get("createtime") or ""),
            str(item.get("message_type") or ""),
            str(item.get("content") or ""),
        ]
    )
    return "douyin:web:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _collision_message_id(team_id: int, contact_id: str, item: dict[str, Any]) -> str:
    """第三方偶尔复用 server_message_id，用完整消息指纹避免误去重。"""
    raw = "|".join(
        [
            str(team_id),
            contact_id,
            str(item.get("server_message_id") or item.get("msg_id") or ""),
            str(item.get("from_open_id") or ""),
            str(item.get("createtime") or ""),
            str(item.get("message_type") or ""),
            str(item.get("content") or ""),
        ]
    )
    return "douyin:web:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _save_contact(
    team_id: int,
    account: dict[str, Any],
    session: dict[str, Any],
) -> None:
    contact_id = str(
        session.get("from_open_id")
        or session.get("open_id")
        or session.get("id")
        or ""
    ).strip()
    if not contact_id:
        return
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO kellai_douyin_web_contacts
                (team_id, contact_id, account_id, account_name, conversation_id,
                 contact_name, avatar, latest_content, latest_message_type,
                 latest_message_at, unread_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(team_id, contact_id) DO UPDATE SET
                account_id = excluded.account_id,
                account_name = excluded.account_name,
                conversation_id = excluded.conversation_id,
                contact_name = excluded.contact_name,
                avatar = excluded.avatar,
                latest_content = excluded.latest_content,
                latest_message_type = excluded.latest_message_type,
                latest_message_at = excluded.latest_message_at,
                unread_count = excluded.unread_count,
                updated_at = excluded.updated_at
            """,
            (
                int(team_id),
                contact_id,
                str(account.get("id") or session.get("member_id") or ""),
                str(account.get("name") or account.get("server_name") or ""),
                str(session.get("conversation_short_id") or ""),
                str(session.get("nick_name") or session.get("nickname") or contact_id),
                str(session.get("avatar") or ""),
                _message_content(
                    str(session.get("message_type") or "text"),
                    session.get("content"),
                ),
                str(session.get("message_type") or "text"),
                _timestamp(session.get("createtime")),
                int(session.get("not_read_msg_num") or 0),
                _now_iso(),
            ),
        )


def _ingest_message(
    *,
    team_id: int,
    account: dict[str, Any],
    session: dict[str, Any],
    item: dict[str, Any],
) -> bool:
    contact_id = str(
        session.get("from_open_id")
        or session.get("open_id")
        or session.get("id")
        or ""
    ).strip()
    if not contact_id:
        return False
    customer_open_id = str(session.get("from_open_id") or contact_id)
    from_open_id = str(item.get("from_open_id") or "")
    direction = "inbound" if not from_open_id or from_open_id == customer_open_id else "outbound"
    message_type = str(item.get("message_type") or "text")
    content = _message_content(message_type, item.get("content"), item.get("extend"))
    if not content:
        return False
    message_id = _stable_message_id(team_id, contact_id, item)
    created_at = _timestamp(item.get("createtime"))
    ensure_messages_schema()
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        existing = conn.execute(
            """
            SELECT content, direction, created_at
            FROM kellai_messages
            WHERE team_id = ? AND id = ?
            LIMIT 1
            """,
            (int(team_id), message_id),
        ).fetchone()
        if existing:
            if (
                str(existing[0] or "") == content
                and str(existing[1] or "") == direction
                and str(existing[2] or "") == created_at
            ):
                return False
            message_id = _collision_message_id(team_id, contact_id, item)
            if conn.execute(
                "SELECT 1 FROM kellai_messages WHERE team_id = ? AND id = ? LIMIT 1",
                (int(team_id), message_id),
            ).fetchone():
                return False
    provisional_customer_id = 0
    if direction == "outbound":
        provisional_customer_id = _remove_matching_desktop_provisional(
            team_id=team_id,
            contact_id=contact_id,
            content=content,
            created_at=created_at,
        )
    contact_name = str(
        session.get("nick_name")
        or session.get("nickname")
        or item.get("nick_name")
        or contact_id
    )
    metadata = {
        "source": "douyin_web_portal",
        "team_id": int(team_id),
        "portal_account_id": str(account.get("id") or session.get("member_id") or ""),
        "portal_account_name": str(account.get("name") or account.get("server_name") or ""),
        "conversation_short_id": str(session.get("conversation_short_id") or ""),
        "server_message_id": str(item.get("server_message_id") or item.get("msg_id") or ""),
        "remote_message_type": message_type,
        "avatar": str(session.get("avatar") or item.get("avatar") or ""),
    }
    push_inbox(
        "douyin",
        contact_id=contact_id,
        contact_name=contact_name,
        direction=direction,
        content=content,
        content_type="text",
        metadata=metadata,
        msg_id=message_id,
    )
    saved = save_message(
        UnifiedMessage(
            id=message_id,
            customer_id=provisional_customer_id,
            channel_type="douyin",
            contact_id=contact_id,
            contact_name=contact_name,
            direction=direction,
            content=content,
            content_type="text",
            metadata=metadata,
            created_at=created_at,
        )
    )
    if direction == "inbound":
        try:
            from app.services.auto_reply_runtime import enqueue_message

            enqueue_message(saved)
        except Exception:
            logger.warning(
                "抖音客服网页消息已保存但自动回复任务入队失败: message_id=%s",
                message_id,
                exc_info=True,
            )
    mark_inbox_consumed([message_id], team_id=team_id)
    return bool(saved.id)


def _remove_matching_desktop_provisional(
    *,
    team_id: int,
    contact_id: str,
    content: str,
    created_at: str,
) -> int:
    """用网页同步的真实消息替换桌面自动化产生的临时出站记录。"""
    try:
        remote_at = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        remote_at = datetime.now(timezone.utc)
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        rows = conn.execute(
            """
            SELECT id, customer_id, metadata_json, created_at
            FROM kellai_messages
            WHERE team_id = ?
              AND channel_type = 'douyin'
              AND contact_id = ?
              AND direction = 'outbound'
              AND content = ?
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (int(team_id), str(contact_id), str(content)),
        ).fetchall()
        for row in rows:
            try:
                metadata = json.loads(row[2] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if metadata.get("source") != "douyin_desktop_automation":
                continue
            try:
                local_at = datetime.fromisoformat(str(row[3]).replace("Z", "+00:00"))
            except ValueError:
                continue
            if abs((remote_at - local_at).total_seconds()) > 300:
                continue
            conn.execute(
                "DELETE FROM kellai_messages WHERE team_id = ? AND id = ?",
                (int(team_id), str(row[0])),
            )
            conn.commit()
            return int(row[1] or 0)
    return 0


async def sync_messages(
    team_id: int,
    *,
    max_conversations: int = 200,
    history_limit: int = 20,
) -> dict[str, Any]:
    token = _stored_token(team_id)
    try:
        accounts_raw = await _post(token, "service/TodayShunt/index")
        accounts = accounts_raw if isinstance(accounts_raw, list) else []
        sessions: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            raw = await _post(
                token,
                "service/TodayShunt/getSessionList",
                {"id": account.get("id")},
            )
            for session in raw if isinstance(raw, list) else []:
                if not isinstance(session, dict):
                    continue
                _save_contact(team_id, account, session)
                sessions.append((account, session))
                if len(sessions) >= int(max_conversations):
                    break
            if len(sessions) >= int(max_conversations):
                break

        semaphore = asyncio.Semaphore(6)

        async def fetch_history(
            account: dict[str, Any],
            session: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
            async with semaphore:
                data = await _post(
                    token,
                    "service/TodayShunt/getMsgLog",
                    {
                        "page": 1,
                        "limit": max(1, min(int(history_limit), 100)),
                        "conversation_short_id": session.get("conversation_short_id"),
                    },
                )
            items = data.get("data", []) if isinstance(data, dict) else []
            return account, session, [item for item in items if isinstance(item, dict)]

        histories = await asyncio.gather(
            *(fetch_history(account, session) for account, session in sessions),
            return_exceptions=True,
        )
        ingested = 0
        history_errors = 0
        for result in histories:
            if isinstance(result, Exception):
                history_errors += 1
                continue
            account, session, items = result
            for item in reversed(items):
                if _ingest_message(
                    team_id=team_id,
                    account=account,
                    session=session,
                    item=item,
                ):
                    ingested += 1
        _update_state(
            team_id,
            status="connected",
            last_sync_at=_now_iso(),
            last_error="" if history_errors == 0 else f"{history_errors} 个会话历史拉取失败",
        )
        return {
            "accounts": len(accounts),
            "contacts": len(sessions),
            "messages": ingested,
            "history_errors": history_errors,
        }
    except DouyinWebPortalAuthError as exc:
        _update_state(team_id, status="expired", monitor_enabled=0, last_error=str(exc))
        raise
    except Exception as exc:
        _update_state(team_id, status="error", last_error=str(exc))
        raise


async def _handle_websocket_payload(team_id: int, payload: dict[str, Any]) -> bool:
    if str(payload.get("type") or "") != "webhooks":
        return False
    data = payload.get("data")
    if not isinstance(data, dict) or str(data.get("msg_type") or "") != "private_msg":
        return False
    member = data.get("memberInfo") if isinstance(data.get("memberInfo"), dict) else {}
    item = data.get("msgData") if isinstance(data.get("msgData"), dict) else {}
    session = data.get("userInfo") if isinstance(data.get("userInfo"), dict) else {}
    _save_contact(team_id, member, session)
    ingested = _ingest_message(
        team_id=team_id,
        account=member,
        session=session,
        item=item,
    )
    if ingested:
        _update_state(team_id, last_message_at=_now_iso(), status="connected", last_error="")
    return ingested


def _history_sync_interval() -> float:
    raw = os.environ.get("KELLAI_DOUYIN_WEB_SYNC_INTERVAL", "15")
    try:
        return max(5.0, min(float(raw), 300.0))
    except (TypeError, ValueError):
        return 15.0


async def _periodic_history_sync(team_id: int) -> None:
    """补拉网页端发送的消息；该类消息不一定会通过私信 WebSocket 推送。"""
    while True:
        await asyncio.sleep(_history_sync_interval())
        try:
            await sync_messages(team_id, max_conversations=300, history_limit=100)
        except asyncio.CancelledError:
            raise
        except DouyinWebPortalAuthError:
            return
        except Exception as exc:
            logger.debug(
                "抖音客服网页历史补拉失败: team_id=%s err=%s",
                team_id,
                exc,
            )


async def _monitor_loop(team_id: int) -> None:
    import websockets

    token = _stored_token(team_id)
    backoff = 1.0
    history_task = asyncio.create_task(
        _periodic_history_sync(team_id),
        name=f"kellai-douyin-web-history-{team_id}",
    )
    try:
        while True:
            try:
                ws_url = await _post(token, "service/WebSocket/getWebSocketUrl")
                if not isinstance(ws_url, str) or not ws_url.startswith(("ws://", "wss://")):
                    raise DouyinWebPortalError("客服网页未返回有效 WebSocket 地址")
                async with websockets.connect(
                    ws_url,
                    open_timeout=20,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=8 * 1024 * 1024,
                ) as socket:
                    backoff = 1.0
                    _update_state(
                        team_id,
                        monitor_enabled=1,
                        status="connected",
                        last_error="",
                    )
                    async for raw in socket:
                        try:
                            payload = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if not isinstance(payload, dict):
                            continue
                        if str(payload.get("type") or "") == "init":
                            client_id = str(payload.get("client_id") or "")
                            if client_id:
                                await _post(
                                    token,
                                    "service/WebSocket/bind",
                                    {"clientId": client_id},
                                )
                                await _post(
                                    token,
                                    "service/service/setServerOnline",
                                    {"is_on_line": 1},
                                )
                            continue
                        await _handle_websocket_payload(team_id, payload)
            except asyncio.CancelledError:
                raise
            except DouyinWebPortalAuthError as exc:
                _update_state(
                    team_id,
                    status="expired",
                    monitor_enabled=0,
                    last_error=str(exc),
                )
                return
            except Exception as exc:
                logger.warning("抖音客服网页实时连接断开: team_id=%s err=%s", team_id, exc)
                _update_state(team_id, status="reconnecting", last_error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
    finally:
        history_task.cancel()
        try:
            await history_task
        except asyncio.CancelledError:
            pass
        _update_state(team_id, monitor_enabled=0)


async def start_monitor(team_id: int) -> dict[str, Any]:
    token = _stored_token(team_id)
    if not token:
        raise DouyinWebPortalAuthError("尚未绑定抖音客服网页")
    async with _MONITOR_LOCK:
        current = _MONITOR_TASKS.get(int(team_id))
        if current and not current.done():
            return status(team_id)
        task = asyncio.create_task(
            _monitor_loop(int(team_id)),
            name=f"kellai-douyin-web-{int(team_id)}",
        )
        _MONITOR_TASKS[int(team_id)] = task
    _update_state(team_id, monitor_enabled=1, status="connecting", last_error="")
    return status(team_id)


async def resume_connected_monitors() -> dict[str, int]:
    """后端重启后自动恢复已绑定且未过期的网站私信监听。"""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT team_id
            FROM kellai_douyin_web_portal
            WHERE token_enc <> ''
              AND status NOT IN ('expired', 'disconnected')
            ORDER BY team_id
            """
        ).fetchall()

    started = 0
    failed = 0
    for row in rows:
        team_id = int(row["team_id"])
        try:
            await start_monitor(team_id)
            started += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "恢复抖音客服网页实时监听失败: team_id=%s err=%s",
                team_id,
                exc,
            )
    return {"started": started, "failed": failed}


async def stop_monitor(team_id: int) -> dict[str, Any]:
    async with _MONITOR_LOCK:
        task = _MONITOR_TASKS.pop(int(team_id), None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    token = _stored_token(team_id)
    if token:
        try:
            await _post(token, "service/service/websocketClose")
        except Exception:
            logger.debug("通知第三方客服网页关闭 WebSocket 失败", exc_info=True)
    _update_state(team_id, monitor_enabled=0, status="connected")
    return status(team_id)


def list_contacts(team_id: int, limit: int = 500) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM kellai_douyin_web_contacts
            WHERE team_id = ?
            ORDER BY latest_message_at DESC, updated_at DESC
            LIMIT ?
            """,
            (int(team_id), max(1, min(int(limit), 1000))),
        ).fetchall()
    return [dict(row) for row in rows]


async def stream_status(team_id: int) -> AsyncIterator[str]:
    """供前端以 NDJSON 观察同步与实时监控状态。"""
    previous = ""
    while True:
        payload = status(team_id)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if encoded != previous:
            previous = encoded
            yield encoded + "\n"
        await asyncio.sleep(1.0)
