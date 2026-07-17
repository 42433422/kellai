"""企业微信服务商第三方应用授权与外部联系人同步。

服务商级密钥仅从环境变量读取；企业授权按客来来 team_id 写入统一 SQLite。
桌面端只接收安装 URL 和脱敏状态，不接触 SuiteSecret/permanent_code。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.services.crm_store import _crm_db_path


WECOM_API_BASE = "https://qyapi.weixin.qq.com"
WECOM_INSTALL_BASE = "https://open.work.weixin.qq.com/3rdapp/install"
WECOM_BRIDGE_KEYCHAIN_SERVICE = "com.kellai.wework-bridge"
WECOM_INSTALL_CALLBACK_GRACE_SECONDS = 600


class WeWorkSuiteError(RuntimeError):
    """可安全返回给客户端的企业微信服务商错误。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def suite_config() -> dict[str, str]:
    public_base_url = _env("KELLAI_PUBLIC_BASE_URL").rstrip("/")
    return {
        "suite_id": _env("KELLAI_WECOM_SUITE_ID"),
        "suite_secret": _env("KELLAI_WECOM_SUITE_SECRET"),
        "token": _env("KELLAI_WECOM_TOKEN"),
        "encoding_aes_key": _env("KELLAI_WECOM_ENCODING_AES_KEY"),
        "public_base_url": public_base_url,
        # 0=正式授权，1=未发布应用的测试授权。生产发布后应显式改为 0。
        "auth_type": _env("KELLAI_WECOM_AUTH_TYPE") or "0",
    }


def suite_readiness() -> dict[str, Any]:
    cfg = suite_config()
    required = ("suite_id", "suite_secret", "token", "encoding_aes_key", "public_base_url")
    missing = [name for name in required if not cfg[name]]
    callback_url = f"{cfg['public_base_url']}/api/kellai/webhook/wework/suite" if cfg["public_base_url"] else ""
    install_callback_url = (
        f"{cfg['public_base_url']}/api/kellai/channels/wework/install/callback"
        if cfg["public_base_url"]
        else ""
    )
    public_https = cfg["public_base_url"].startswith("https://")
    return {
        "configured": not missing and public_https,
        "missing": missing,
        "public_https": public_https,
        "callback_url": callback_url,
        "install_callback_url": install_callback_url,
        "suite_id": cfg["suite_id"],
        "has_suite_ticket": bool(load_suite_ticket()),
    }


def _keychain_bridge_key() -> str:
    """Read the per-device bridge credential without shipping it in the desktop bundle."""
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
                WECOM_BRIDGE_KEYCHAIN_SERVICE,
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
    bridge_key = _env("KELLAI_WECOM_REMOTE_BRIDGE_KEY") or _keychain_bridge_key()
    base_url = _env("KELLAI_WECOM_REMOTE_BASE_URL")
    if bridge_key and not base_url:
        base_url = "https://xiu-ci.com"
    return {"base_url": base_url.rstrip("/"), "bridge_key": bridge_key}


def remote_bridge_enabled() -> bool:
    cfg = remote_bridge_config()
    return bool(cfg["base_url"] and cfg["bridge_key"])


def verify_bridge_key(value: str) -> None:
    expected = _env("KELLAI_WECOM_BRIDGE_KEY")
    if not expected:
        raise WeWorkSuiteError("企业微信远端桥接未启用")
    if not value or not hmac.compare_digest(expected, value.strip()):
        raise WeWorkSuiteError("企业微信远端桥接认证失败")


async def _remote_bridge_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = remote_bridge_config()
    if not cfg["base_url"] or not cfg["bridge_key"]:
        raise WeWorkSuiteError("企业微信远端桥接未配置")
    url = f"{cfg['base_url']}/api/kellai/internal/wework/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=payload,
                headers={"X-Kellai-WeWork-Bridge-Key": cfg["bridge_key"]},
            )
    except httpx.HTTPError as exc:
        raise WeWorkSuiteError("企业微信远端服务暂时不可用") from exc
    try:
        body = response.json()
    except Exception as exc:
        raise WeWorkSuiteError(f"企业微信远端服务返回非 JSON：HTTP {response.status_code}") from exc
    if response.status_code >= 400 or body.get("success") is False:
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
        raise WeWorkSuiteError(
            str(body.get("error") or body.get("message") or detail.get("message") or response.status_code)
        )
    data = body.get("data", body)
    return data if isinstance(data, dict) else {"data": data}


async def remote_suite_readiness() -> dict[str, Any]:
    data = await _remote_bridge_request("GET", "readiness")
    data["mode"] = "remote_ssot"
    return data


async def remote_create_install_url(*, team_id: int, user_id: int) -> dict[str, Any]:
    return await _remote_bridge_request(
        "POST", "install", params={"team_id": int(team_id), "user_id": int(user_id)}
    )


async def remote_get_install_status(*, state: str, team_id: int) -> dict[str, Any]:
    return await _remote_bridge_request(
        "GET", "install/status", params={"state": state, "team_id": int(team_id)}
    )


async def remote_sync_external_customers(team_id: int, *, limit: int = 500) -> dict[str, Any]:
    data = await _remote_bridge_request(
        "POST", "customers/sync", params={"team_id": int(team_id), "limit": int(limit)}
    )
    customers = data.get("customers") if isinstance(data.get("customers"), list) else []
    data["local_imported"] = _import_customers_to_pipeline(team_id, customers)
    return data


async def remote_list_customers(team_id: int, *, limit: int = 500) -> list[dict[str, Any]]:
    data = await _remote_bridge_request(
        "GET", "customers", params={"team_id": int(team_id), "limit": int(limit)}
    )
    customers = data.get("customers")
    return customers if isinstance(customers, list) else []


async def remote_list_acquisition_members(team_id: int) -> dict[str, Any]:
    return await _remote_bridge_request(
        "GET", "acquisition/members", params={"team_id": int(team_id)}
    )


async def remote_create_acquisition_link(
    team_id: int,
    *,
    link_name: str,
    userids: list[str],
    skip_verify: bool = True,
) -> dict[str, Any]:
    return await _remote_bridge_request(
        "POST",
        "acquisition/links",
        params={"team_id": int(team_id)},
        payload={
            "link_name": link_name,
            "userids": userids,
            "skip_verify": bool(skip_verify),
        },
    )


def _require_suite_config(*, require_ticket: bool = False) -> dict[str, str]:
    cfg = suite_config()
    missing = [
        key
        for key in ("suite_id", "suite_secret", "token", "encoding_aes_key", "public_base_url")
        if not cfg[key]
    ]
    if missing:
        raise WeWorkSuiteError("企业微信服务商配置未完成：" + ", ".join(missing))
    if not cfg["public_base_url"].startswith("https://"):
        raise WeWorkSuiteError("KELLAI_PUBLIC_BASE_URL 必须是公网 HTTPS 地址")
    if require_ticket and not load_suite_ticket():
        raise WeWorkSuiteError("尚未收到企业微信 suite_ticket，请先保存指令回调 URL 并等待推送")
    return cfg


def _require_callback_config() -> dict[str, str]:
    """Return the subset needed while WeCom validates callback URLs.

    During third-party app creation, WeCom validates the callback before the
    SuiteID/SuiteSecret are available to the service.  Signature verification
    and AES decryption only require the callback Token and EncodingAESKey.
    """
    cfg = suite_config()
    missing = [key for key in ("token", "encoding_aes_key") if not cfg[key]]
    if missing:
        raise WeWorkSuiteError("企业微信回调配置未完成：" + ", ".join(missing))
    try:
        aes_key = base64.b64decode(cfg["encoding_aes_key"] + "=", validate=True)
    except Exception as exc:
        raise WeWorkSuiteError("企业微信 EncodingAESKey 格式无效") from exc
    if len(aes_key) != 32:
        raise WeWorkSuiteError("企业微信 EncodingAESKey 长度无效")
    return cfg


def _fernet() -> Fernet:
    seed = _env("KELLAI_WECOM_STORAGE_KEY") or _env("KELLAI_WECOM_SUITE_SECRET")
    if not seed:
        raise WeWorkSuiteError("缺少 KELLAI_WECOM_STORAGE_KEY 或 KELLAI_WECOM_SUITE_SECRET")
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
        raise WeWorkSuiteError("企业微信授权密文无法解密，请检查存储密钥是否变化") from exc


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


def ensure_schema() -> None:
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kellai_wework_suite_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                suite_ticket_enc TEXT NOT NULL DEFAULT '',
                ticket_updated_at TEXT NOT NULL DEFAULT '',
                suite_access_token_enc TEXT NOT NULL DEFAULT '',
                suite_access_token_expires_at INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS kellai_wework_install_sessions (
                state TEXT PRIMARY KEY,
                team_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                auth_corpid TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                expires_at INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_wework_install_team
                ON kellai_wework_install_sessions(team_id, created_at);
            CREATE TABLE IF NOT EXISTS kellai_wework_authorizations (
                team_id INTEGER PRIMARY KEY,
                auth_corpid TEXT NOT NULL UNIQUE,
                permanent_code_enc TEXT NOT NULL,
                agent_id TEXT NOT NULL DEFAULT '',
                corp_name TEXT NOT NULL DEFAULT '',
                auth_info_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'authorized',
                authorized_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                revoked_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS kellai_wework_customers (
                team_id INTEGER NOT NULL,
                external_userid TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '',
                contact_type INTEGER NOT NULL DEFAULT 0,
                gender INTEGER NOT NULL DEFAULT 0,
                unionid TEXT NOT NULL DEFAULT '',
                follow_users_json TEXT NOT NULL DEFAULT '[]',
                raw_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (team_id, external_userid)
            );
            """
        )


def save_suite_ticket(ticket: str) -> None:
    clean = (ticket or "").strip()
    if not clean:
        raise WeWorkSuiteError("suite_ticket 为空")
    now = _now_iso()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO kellai_wework_suite_state
                (id, suite_ticket_enc, ticket_updated_at, updated_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                suite_ticket_enc=excluded.suite_ticket_enc,
                ticket_updated_at=excluded.ticket_updated_at,
                suite_access_token_enc='',
                suite_access_token_expires_at=0,
                updated_at=excluded.updated_at
            """,
            (_encrypt(clean), now, now),
        )


def load_suite_ticket() -> str:
    ensure_schema()
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        row = conn.execute(
            "SELECT suite_ticket_enc FROM kellai_wework_suite_state WHERE id = 1"
        ).fetchone()
    return _decrypt(str(row[0])) if row and row[0] else ""


def _signature(token: str, timestamp: str, nonce: str, encrypted: str) -> str:
    pieces = sorted([token, timestamp, nonce, encrypted])
    return hashlib.sha1("".join(pieces).encode("utf-8")).hexdigest()


def verify_signature(signature: str, timestamp: str, nonce: str, encrypted: str) -> None:
    cfg = _require_callback_config()
    expected = _signature(cfg["token"], timestamp, nonce, encrypted)
    if not signature or not hmac.compare_digest(expected, signature):
        raise WeWorkSuiteError("企业微信回调签名校验失败")


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise WeWorkSuiteError("企业微信回调解密结果为空")
    pad = data[-1]
    if pad < 1 or pad > 32 or data[-pad:] != bytes([pad]) * pad:
        raise WeWorkSuiteError("企业微信回调 PKCS7 填充无效")
    return data[:-pad]


def decrypt_callback(encrypted: str, *, validate_suite_id: bool = True) -> str:
    cfg = _require_callback_config()
    try:
        aes_key = base64.b64decode(cfg["encoding_aes_key"] + "=")
        cipher_text = base64.b64decode(encrypted)
        decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16])).decryptor()
        plain = _pkcs7_unpad(decryptor.update(cipher_text) + decryptor.finalize())
        msg_len = struct.unpack("!I", plain[16:20])[0]
        message = plain[20 : 20 + msg_len]
        receive_id = plain[20 + msg_len :].decode("utf-8", errors="replace")
    except WeWorkSuiteError:
        raise
    except Exception as exc:
        raise WeWorkSuiteError("企业微信回调解密失败") from exc
    if validate_suite_id and cfg["suite_id"] and receive_id and receive_id != cfg["suite_id"]:
        raise WeWorkSuiteError("企业微信回调 SuiteID 不匹配")
    return message.decode("utf-8")


def parse_encrypted_xml(raw_body: bytes) -> str:
    try:
        root = ET.fromstring(raw_body.decode("utf-8"))
        return (root.findtext("Encrypt") or "").strip()
    except Exception as exc:
        raise WeWorkSuiteError("企业微信回调 XML 无效") from exc


def parse_plain_event(xml_text: str) -> dict[str, str]:
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        raise WeWorkSuiteError("企业微信回调明文 XML 无效") from exc
    return {child.tag: (child.text or "").strip() for child in root}


def _single_pending_install_state(event_state: str = "") -> str:
    now = int(time.time())
    with _conn() as conn:
        state = (event_state or "").strip()
        if state:
            row = conn.execute(
                """
                SELECT state FROM kellai_wework_install_sessions
                WHERE state=? AND status='pending' AND COALESCE(error, '')=''
                  AND expires_at>=?
                """,
                (state, now - WECOM_INSTALL_CALLBACK_GRACE_SECONDS),
            ).fetchone()
            if row:
                return str(row["state"])
        rows = conn.execute(
            """
            SELECT state FROM kellai_wework_install_sessions
            WHERE status='pending' AND COALESCE(error, '')='' AND expires_at>=?
            ORDER BY created_at DESC LIMIT 2
            """,
            (now - WECOM_INSTALL_CALLBACK_GRACE_SECONDS,),
        ).fetchall()
    return str(rows[0]["state"]) if len(rows) == 1 else ""


async def handle_suite_event(event: dict[str, str]) -> dict[str, Any]:
    info_type = event.get("InfoType", "")
    if info_type == "suite_ticket":
        save_suite_ticket(event.get("SuiteTicket", ""))
        return {"info_type": info_type, "saved": True}
    if info_type == "create_auth":
        auth_code = event.get("AuthCode", "")
        state = _single_pending_install_state(event.get("State", ""))
        if not auth_code:
            raise WeWorkSuiteError("create_auth 回调缺少 AuthCode")
        if not state:
            return {"info_type": info_type, "ignored": True, "reason": "no_unique_pending_install"}
        result = await complete_install(state=state, auth_code=auth_code)
        return {
            "info_type": info_type,
            "authorized": bool(result.get("authorized")),
            "auth_corpid": str(result.get("auth_corpid") or ""),
        }
    if info_type in {"cancel_auth", "change_auth"}:
        corp_id = event.get("AuthCorpId", "")
        with _conn() as conn:
            if info_type == "cancel_auth":
                conn.execute(
                    "UPDATE kellai_wework_authorizations SET status='revoked', revoked_at=?, updated_at=? WHERE auth_corpid=?",
                    (_now_iso(), _now_iso(), corp_id),
                )
            else:
                conn.execute(
                    "UPDATE kellai_wework_authorizations SET updated_at=? WHERE auth_corpid=?",
                    (_now_iso(), corp_id),
                )
        return {"info_type": info_type, "auth_corpid": corp_id}
    return {"info_type": info_type, "ignored": True}


async def _post_json(path: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{WECOM_API_BASE}{path}", params=params, json=payload)
    try:
        body = response.json()
    except Exception as exc:
        raise WeWorkSuiteError(f"企业微信接口返回非 JSON：HTTP {response.status_code}") from exc
    if response.status_code >= 400 or int(body.get("errcode", 0) or 0) != 0:
        raise WeWorkSuiteError(
            f"企业微信接口失败：errcode={body.get('errcode')} errmsg={body.get('errmsg') or response.status_code}"
        )
    return body


async def _get_json(path: str, *, params: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{WECOM_API_BASE}{path}", params=params)
    try:
        body = response.json()
    except Exception as exc:
        raise WeWorkSuiteError(f"企业微信接口返回非 JSON：HTTP {response.status_code}") from exc
    if response.status_code >= 400 or int(body.get("errcode", 0) or 0) != 0:
        raise WeWorkSuiteError(
            f"企业微信接口失败：errcode={body.get('errcode')} errmsg={body.get('errmsg') or response.status_code}"
        )
    return body


async def get_suite_access_token(*, force: bool = False) -> str:
    cfg = _require_suite_config(require_ticket=True)
    ensure_schema()
    if not force:
        with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
            row = conn.execute(
                "SELECT suite_access_token_enc, suite_access_token_expires_at FROM kellai_wework_suite_state WHERE id = 1"
            ).fetchone()
        if row and row[0] and int(row[1] or 0) > int(time.time()) + 60:
            return _decrypt(str(row[0]))
    body = await _post_json(
        "/cgi-bin/service/get_suite_token",
        payload={
            "suite_id": cfg["suite_id"],
            "suite_secret": cfg["suite_secret"],
            "suite_ticket": load_suite_ticket(),
        },
    )
    token = str(body.get("suite_access_token") or "")
    if not token:
        raise WeWorkSuiteError("企业微信未返回 suite_access_token")
    expires_at = int(time.time()) + max(60, int(body.get("expires_in", 7200) or 7200))
    with _conn() as conn:
        conn.execute(
            """
            UPDATE kellai_wework_suite_state
            SET suite_access_token_enc=?, suite_access_token_expires_at=?, updated_at=?
            WHERE id=1
            """,
            (_encrypt(token), expires_at, _now_iso()),
        )
    return token


def create_install_session(*, team_id: int, user_id: int, ttl: int = 600) -> str:
    if team_id <= 0 or user_id <= 0:
        raise WeWorkSuiteError("当前账号没有有效团队，无法绑定企业微信")
    state = secrets.token_urlsafe(32)
    now = _now_iso()
    with _conn() as conn:
        # 同一客来来团队只保留一个可完成的安装会话，避免企业微信
        # create_auth 回调无法判断应该绑定哪一个 state。
        conn.execute(
            """
            UPDATE kellai_wework_install_sessions
            SET status='expired', expires_at=?, error='superseded_by_new_install'
            WHERE team_id=? AND user_id=? AND status='pending'
            """,
            (int(time.time()) - 1, team_id, user_id),
        )
        conn.execute(
            """
            INSERT INTO kellai_wework_install_sessions
                (state, team_id, user_id, status, expires_at, created_at)
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (state, team_id, user_id, int(time.time()) + ttl, now),
        )
    return state


async def create_install_url(*, team_id: int, user_id: int) -> dict[str, Any]:
    cfg = _require_suite_config(require_ticket=True)
    suite_token = await get_suite_access_token()
    pre_auth = await _post_json(
        "/cgi-bin/service/get_pre_auth_code",
        params={"suite_access_token": suite_token},
        payload={},
    )
    pre_auth_code = str(pre_auth.get("pre_auth_code") or "")
    if not pre_auth_code:
        raise WeWorkSuiteError("企业微信未返回 pre_auth_code")
    try:
        auth_type = int(cfg["auth_type"])
    except (TypeError, ValueError) as exc:
        raise WeWorkSuiteError("KELLAI_WECOM_AUTH_TYPE 必须为 0 或 1") from exc
    if auth_type not in {0, 1}:
        raise WeWorkSuiteError("KELLAI_WECOM_AUTH_TYPE 必须为 0 或 1")
    # 未发布应用必须先把本次预授权会话设置为测试授权，否则企业微信的
    # /3rdapp/install 页面会把应用判定为“已下线”。正式发布后使用 0。
    await _post_json(
        "/cgi-bin/service/set_session_info",
        params={"suite_access_token": suite_token},
        payload={
            "pre_auth_code": pre_auth_code,
            "session_info": {"auth_type": auth_type},
        },
    )
    pre_auth_ttl = max(60, min(3600, int(pre_auth.get("expires_in", 600) or 600)))
    state = create_install_session(team_id=team_id, user_id=user_id, ttl=pre_auth_ttl)
    redirect_uri = f"{cfg['public_base_url']}/api/kellai/channels/wework/install/callback"
    query = urlencode(
        {
            "suite_id": cfg["suite_id"],
            "pre_auth_code": pre_auth_code,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    install_url = f"{WECOM_INSTALL_BASE}?{query}"
    return {
        "state": state,
        "install_url": install_url,
        "qr_text": install_url,
        "expires_in": pre_auth_ttl,
        "mode": "suite_install",
        "auth_type": auth_type,
    }


def _load_install_session(state: str) -> sqlite3.Row | None:
    ensure_schema()
    with sqlite3.connect(str(_crm_db_path()), timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM kellai_wework_install_sessions WHERE state=?",
            ((state or "").strip(),),
        ).fetchone()


async def complete_install(*, state: str, auth_code: str) -> dict[str, Any]:
    session = _load_install_session(state)
    if not session:
        raise WeWorkSuiteError("无效的企业微信安装 state")
    status = str(session["status"] or "pending")
    if status == "authorized":
        return get_install_status(state=state, team_id=int(session["team_id"]))
    if status != "pending" or str(session["error"] or ""):
        raise WeWorkSuiteError("企业微信安装 state 已失效")
    if int(session["expires_at"] or 0) < int(time.time()) - WECOM_INSTALL_CALLBACK_GRACE_SECONDS:
        raise WeWorkSuiteError("企业微信安装 state 已过期")
    suite_token = await get_suite_access_token()
    try:
        body = await _post_json(
            "/cgi-bin/service/get_permanent_code",
            params={"suite_access_token": suite_token},
            payload={"auth_code": auth_code},
        )
        permanent_code = str(body.get("permanent_code") or "")
        corp = body.get("auth_corp_info") or {}
        auth_corpid = str(corp.get("corpid") or "")
        corp_name = str(corp.get("corp_name") or "")
        agents = ((body.get("auth_info") or {}).get("agent") or [])
        agent_id = str((agents[0] if agents else {}).get("agentid") or "")
        if not permanent_code or not auth_corpid:
            raise WeWorkSuiteError("企业微信未返回 permanent_code/auth_corpid")
        now = _now_iso()
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO kellai_wework_authorizations
                    (team_id, auth_corpid, permanent_code_enc, agent_id, corp_name,
                     auth_info_json, status, authorized_at, updated_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, ?, 'authorized', ?, ?, '')
                ON CONFLICT(team_id) DO UPDATE SET
                    auth_corpid=excluded.auth_corpid,
                    permanent_code_enc=excluded.permanent_code_enc,
                    agent_id=excluded.agent_id,
                    corp_name=excluded.corp_name,
                    auth_info_json=excluded.auth_info_json,
                    status='authorized',
                    authorized_at=excluded.authorized_at,
                    updated_at=excluded.updated_at,
                    revoked_at=''
                """,
                (
                    int(session["team_id"]),
                    auth_corpid,
                    _encrypt(permanent_code),
                    agent_id,
                    corp_name,
                    json.dumps(body, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE kellai_wework_install_sessions
                SET status='authorized', auth_corpid=?, error='', completed_at=?
                WHERE state=?
                """,
                (auth_corpid, now, state),
            )
        return {
            "authorized": True,
            "auth_corpid": auth_corpid,
            "corp_name": corp_name,
            "agent_id": agent_id,
        }
    except Exception as exc:
        with _conn() as conn:
            conn.execute(
                "UPDATE kellai_wework_install_sessions SET status='failed', error=? WHERE state=?",
                (str(exc)[:500], state),
            )
        raise


def get_install_status(*, state: str, team_id: int) -> dict[str, Any]:
    session = _load_install_session(state)
    if not session or int(session["team_id"] or 0) != int(team_id):
        return {"authorized": False, "expired": True}
    status = str(session["status"] or "pending")
    expired = status == "expired" or (
        int(session["expires_at"] or 0) < int(time.time()) and status == "pending"
    )
    result: dict[str, Any] = {
        "authorized": status == "authorized",
        "expired": expired,
        "status": "expired" if expired else status,
    }
    if session["error"]:
        result["error"] = str(session["error"])
    if session["auth_corpid"]:
        result["auth_corpid"] = str(session["auth_corpid"])
    if status == "authorized":
        with _conn() as conn:
            auth = conn.execute(
                "SELECT corp_name, agent_id FROM kellai_wework_authorizations WHERE team_id=?",
                (int(team_id),),
            ).fetchone()
        if auth:
            result.update({"corp_name": str(auth["corp_name"]), "agent_id": str(auth["agent_id"])})
    return result


def _authorization(team_id: int) -> dict[str, str]:
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT auth_corpid, permanent_code_enc, agent_id, corp_name, status
            FROM kellai_wework_authorizations WHERE team_id=?
            """,
            (int(team_id),),
        ).fetchone()
    if not row or str(row["status"]) != "authorized":
        raise WeWorkSuiteError("当前团队尚未授权企业微信")
    return {
        "auth_corpid": str(row["auth_corpid"]),
        "permanent_code": _decrypt(str(row["permanent_code_enc"])),
        "agent_id": str(row["agent_id"]),
        "corp_name": str(row["corp_name"]),
    }


async def get_corp_access_token(team_id: int) -> str:
    auth = _authorization(team_id)
    suite_token = await get_suite_access_token()
    body = await _post_json(
        "/cgi-bin/service/get_corp_token",
        params={"suite_access_token": suite_token},
        payload={
            "auth_corpid": auth["auth_corpid"],
            "permanent_code": auth["permanent_code"],
        },
    )
    token = str(body.get("access_token") or "")
    if not token:
        raise WeWorkSuiteError("企业微信未返回企业 access_token")
    return token


def _save_customers(team_id: int, customers: list[dict[str, Any]]) -> None:
    now = _now_iso()
    with _conn() as conn:
        for item in customers:
            contact = item.get("external_contact") or item
            external_userid = str(contact.get("external_userid") or "")
            if not external_userid:
                continue
            conn.execute(
                """
                INSERT INTO kellai_wework_customers
                    (team_id, external_userid, name, avatar, contact_type, gender,
                     unionid, follow_users_json, raw_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id, external_userid) DO UPDATE SET
                    name=excluded.name,
                    avatar=excluded.avatar,
                    contact_type=excluded.contact_type,
                    gender=excluded.gender,
                    unionid=excluded.unionid,
                    follow_users_json=excluded.follow_users_json,
                    raw_json=excluded.raw_json,
                    updated_at=excluded.updated_at
                """,
                (
                    int(team_id),
                    external_userid,
                    str(contact.get("name") or external_userid),
                    str(contact.get("avatar") or ""),
                    int(contact.get("type", 0) or 0),
                    int(contact.get("gender", 0) or 0),
                    str(contact.get("unionid") or ""),
                    json.dumps(item.get("follow_user") or [], ensure_ascii=False),
                    json.dumps(item, ensure_ascii=False),
                    now,
                ),
            )


def _import_customers_to_pipeline(team_id: int, customers: list[dict[str, Any]]) -> int:
    from app.services.pipeline import _iter_pipeline_docs, create_customer, save_pipeline

    existing: dict[str, dict[str, Any]] = {}
    for doc in _iter_pipeline_docs():
        contacts = doc.get("channel_contacts") if isinstance(doc.get("channel_contacts"), dict) else {}
        external_userid = str(contacts.get("wework") or "")
        if external_userid:
            existing[external_userid] = doc
    imported = 0
    for item in customers:
        contact = item.get("external_contact") or item
        external_userid = str(contact.get("external_userid") or "")
        if not external_userid:
            continue
        name = str(contact.get("name") or external_userid)
        doc = existing.get(external_userid)
        if not doc:
            doc = create_customer(
                {
                    "name": name,
                    "source": "wework",
                    "stage": "idle",
                    "channel_sources": ["wework"],
                    "tags": ["企业微信同步"],
                    "is_demo": False,
                },
                username=name,
            )
            imported += 1
        sources = [str(value) for value in (doc.get("channel_sources") or []) if str(value)]
        if "wework" not in sources:
            sources.append("wework")
        contacts = dict(doc.get("channel_contacts") or {})
        contacts["wework"] = external_userid
        doc["channel_sources"] = sources
        doc["channel_contacts"] = contacts
        doc["team_id"] = int(team_id)
        doc["wework_avatar"] = str(contact.get("avatar") or "")
        save_pipeline(doc)
        existing[external_userid] = doc
    return imported


async def list_acquisition_members(team_id: int) -> dict[str, Any]:
    """列出可绑定到获客链接的客户联系成员。"""
    token = await get_corp_access_token(team_id)
    follow = await _get_json(
        "/cgi-bin/externalcontact/get_follow_user_list",
        params={"access_token": token},
    )
    members: list[dict[str, str]] = []
    for raw_userid in follow.get("follow_user") or []:
        userid = str(raw_userid).strip()
        if not userid:
            continue
        name = userid
        try:
            profile = await _get_json(
                "/cgi-bin/user/get",
                params={"access_token": token, "userid": userid},
            )
            name = str(profile.get("name") or userid)
        except WeWorkSuiteError:
            # 部分第三方应用只获得成员账号，不获得完整通讯录字段；
            # userid 仍可直接用于创建获客链接。
            pass
        members.append({"userid": userid, "name": name})
    return {"members": members, "total": len(members)}


async def create_acquisition_link(
    team_id: int,
    *,
    link_name: str,
    userids: list[str],
    skip_verify: bool = True,
) -> dict[str, Any]:
    """为指定客户联系成员创建可追踪来源的企业微信获客链接。"""
    clean_name = str(link_name or "").strip()
    if not clean_name:
        raise WeWorkSuiteError("请填写获客链接名称")
    if len(clean_name) > 30:
        raise WeWorkSuiteError("获客链接名称不能超过30个字符")
    clean_userids = list(dict.fromkeys(str(value).strip() for value in userids if str(value).strip()))
    if not clean_userids:
        raise WeWorkSuiteError("请至少选择一位跟进员工")
    if len(clean_userids) > 500:
        raise WeWorkSuiteError("单个获客链接最多关联500位员工")

    token = await get_corp_access_token(team_id)
    body = await _post_json(
        "/cgi-bin/externalcontact/customer_acquisition/create_link",
        params={"access_token": token},
        payload={
            "link_name": clean_name,
            "range": {"user_list": clean_userids},
            "skip_verify": bool(skip_verify),
            "mark_source": True,
        },
    )
    raw_link = body.get("link") if isinstance(body.get("link"), dict) else {}
    link = {
        "link_id": str(raw_link.get("link_id") or ""),
        "link_name": str(raw_link.get("link_name") or clean_name),
        "url": str(raw_link.get("url") or ""),
        "create_time": int(raw_link.get("create_time", 0) or 0),
    }
    if not link["link_id"] or not link["url"]:
        raise WeWorkSuiteError("企业微信未返回有效的获客链接")
    return {
        "link": link,
        "userids": clean_userids,
        "skip_verify": bool(skip_verify),
        "mark_source": True,
    }


async def sync_external_customers(team_id: int, *, limit: int = 500) -> dict[str, Any]:
    token = await get_corp_access_token(team_id)
    follow = await _get_json(
        "/cgi-bin/externalcontact/get_follow_user_list",
        params={"access_token": token},
    )
    external_ids: list[str] = []
    seen: set[str] = set()
    for user_id in follow.get("follow_user") or []:
        cursor = ""
        while len(external_ids) < limit:
            params = {"access_token": token, "userid": str(user_id)}
            if cursor:
                params["cursor"] = cursor
            page = await _get_json("/cgi-bin/externalcontact/list", params=params)
            for external_userid in page.get("external_userid") or []:
                value = str(external_userid)
                if value and value not in seen:
                    seen.add(value)
                    external_ids.append(value)
                    if len(external_ids) >= limit:
                        break
            cursor = str(page.get("next_cursor") or "")
            if not cursor or len(external_ids) >= limit:
                break

    customers: list[dict[str, Any]] = []
    for external_userid in external_ids:
        detail = await _get_json(
            "/cgi-bin/externalcontact/get",
            params={"access_token": token, "external_userid": external_userid},
        )
        customers.append(detail)
    _save_customers(team_id, customers)
    imported = _import_customers_to_pipeline(team_id, customers)
    return {
        "synced": len(customers),
        "imported": imported,
        "follow_users": len(follow.get("follow_user") or []),
        "customers": list_customers(team_id, limit=min(limit, 500)),
    }


def list_customers(team_id: int, *, limit: int = 500) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT external_userid, name, avatar, contact_type, gender, unionid,
                   follow_users_json, updated_at
            FROM kellai_wework_customers
            WHERE team_id=? ORDER BY updated_at DESC LIMIT ?
            """,
            (int(team_id), max(1, min(int(limit), 1000))),
        ).fetchall()
    return [
        {
            "external_userid": str(row["external_userid"]),
            "name": str(row["name"]),
            "avatar": str(row["avatar"]),
            "type": int(row["contact_type"] or 0),
            "gender": int(row["gender"] or 0),
            "unionid": str(row["unionid"]),
            "follow_users": json.loads(str(row["follow_users_json"] or "[]")),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]
