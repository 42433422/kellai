from __future__ import annotations

import base64
import struct
import time
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient


def _encrypt_callback(aes_key_text: str, message: bytes, receive_id: bytes) -> str:
    aes_key = base64.b64decode(aes_key_text + "=")
    plain = b"0123456789abcdef" + struct.pack("!I", len(message)) + message + receive_id
    pad = 32 - (len(plain) % 32)
    plain += bytes([pad]) * pad
    encryptor = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16])).encryptor()
    return base64.b64encode(encryptor.update(plain) + encryptor.finalize()).decode("ascii")


@pytest.fixture()
def suite_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KELLAI_WECOM_SUITE_ID", "wwsuite123")
    monkeypatch.setenv("KELLAI_WECOM_SUITE_SECRET", "suite-secret")
    monkeypatch.setenv("KELLAI_WECOM_TOKEN", "callback-token")
    monkeypatch.setenv("KELLAI_WECOM_ENCODING_AES_KEY", "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG")
    monkeypatch.setenv("KELLAI_WECOM_STORAGE_KEY", "storage-key-for-tests")
    monkeypatch.setenv("KELLAI_PUBLIC_BASE_URL", "https://kellai.example.com")
    monkeypatch.setenv("KELLAI_WECOM_AUTH_TYPE", "1")
    from app.services import wework_suite

    wework_suite.ensure_schema()
    return wework_suite


def test_suite_readiness_requires_ticket(suite_env):
    readiness = suite_env.suite_readiness()
    assert readiness["configured"] is True
    assert readiness["has_suite_ticket"] is False
    assert readiness["callback_url"].endswith("/api/kellai/webhook/wework/suite")

    suite_env.save_suite_ticket("ticket-1")
    assert suite_env.suite_readiness()["has_suite_ticket"] is True
    assert suite_env.load_suite_ticket() == "ticket-1"


@pytest.mark.asyncio
async def test_suite_callback_signature_and_aes_decrypt(suite_env):
    message = (
        "<xml><SuiteId>wwsuite123</SuiteId><InfoType>suite_ticket</InfoType>"
        "<SuiteTicket>ticket-2</SuiteTicket></xml>"
    ).encode("utf-8")
    encrypted = _encrypt_callback(
        suite_env.suite_config()["encoding_aes_key"], message, b"wwsuite123"
    )
    timestamp = "1784020000"
    nonce = "nonce-1"
    signature = suite_env._signature("callback-token", timestamp, nonce, encrypted)

    suite_env.verify_signature(signature, timestamp, nonce, encrypted)
    event = suite_env.parse_plain_event(suite_env.decrypt_callback(encrypted))
    assert event["InfoType"] == "suite_ticket"
    await suite_env.handle_suite_event(event)
    assert suite_env.load_suite_ticket() == "ticket-2"


@pytest.mark.parametrize(
    "path",
    [
        "/api/kellai/webhook/wework",
        "/api/kellai/webhook/wework/suite",
    ],
)
def test_callback_url_verification_before_suite_credentials(suite_env, monkeypatch, path):
    monkeypatch.delenv("KELLAI_WECOM_SUITE_ID")
    monkeypatch.delenv("KELLAI_WECOM_SUITE_SECRET")
    encrypted = _encrypt_callback(
        suite_env.suite_config()["encoding_aes_key"], b"verification-ok", b"provisional-app"
    )
    timestamp = "1784020001"
    nonce = "nonce-create"
    signature = suite_env._signature("callback-token", timestamp, nonce, encrypted)

    from app.main import app

    response = TestClient(app).get(
        path,
        params={
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": encrypted,
        },
    )
    assert response.status_code == 200
    assert response.text == "verification-ok"


def test_suite_callback_verification_accepts_provider_corp_receive_id(suite_env):
    """企业微信校验指令回调时可能把服务商 CorpID 放在 ReceiveId。"""
    encrypted = _encrypt_callback(
        suite_env.suite_config()["encoding_aes_key"],
        b"verification-ok",
        b"ww-provider-corp-id",
    )
    timestamp = "1784020002"
    nonce = "nonce-provider"
    signature = suite_env._signature("callback-token", timestamp, nonce, encrypted)

    from app.main import app

    response = TestClient(app).get(
        "/api/kellai/webhook/wework/suite",
        params={
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": encrypted,
        },
    )
    assert response.status_code == 200
    assert response.text == "verification-ok"


def test_suite_callback_event_validates_xml_suite_id(suite_env):
    message = (
        "<xml><SuiteId>wwsuite123</SuiteId><InfoType>suite_ticket</InfoType>"
        "<SuiteTicket>ticket-provider-id</SuiteTicket></xml>"
    ).encode("utf-8")
    encrypted = _encrypt_callback(
        suite_env.suite_config()["encoding_aes_key"], message, b"ww-provider-corp-id"
    )
    timestamp = "1784020003"
    nonce = "nonce-provider-event"
    signature = suite_env._signature("callback-token", timestamp, nonce, encrypted)

    from app.main import app

    response = TestClient(app).post(
        "/api/kellai/webhook/wework/suite",
        params={"msg_signature": signature, "timestamp": timestamp, "nonce": nonce},
        content=f"<xml><Encrypt>{encrypted}</Encrypt></xml>",
    )
    assert response.status_code == 200
    assert response.text == "success"
    assert suite_env.load_suite_ticket() == "ticket-provider-id"


def test_internal_bridge_requires_scoped_key(suite_env, monkeypatch):
    monkeypatch.setenv("KELLAI_WECOM_BRIDGE_KEY", "bridge-key-for-tests")
    from app.main import app

    client = TestClient(app)
    denied = client.get("/api/kellai/internal/wework/readiness")
    assert denied.status_code == 403

    allowed = client.get(
        "/api/kellai/internal/wework/readiness",
        headers={"X-Kellai-WeWork-Bridge-Key": "bridge-key-for-tests"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["data"]["configured"] is True


def test_new_install_session_supersedes_previous_pending(suite_env):
    first = suite_env.create_install_session(team_id=7, user_id=9)
    second = suite_env.create_install_session(team_id=7, user_id=9)

    assert first != second
    first_status = suite_env.get_install_status(state=first, team_id=7)
    second_status = suite_env.get_install_status(state=second, team_id=7)
    assert first_status["status"] == "expired"
    assert first_status["expired"] is True
    assert second_status["status"] == "pending"


@pytest.mark.asyncio
async def test_create_install_url_is_scoped_to_team(suite_env, monkeypatch):
    suite_env.save_suite_ticket("ticket-1")

    async def fake_suite_token(*, force=False):
        return "suite-token"

    calls = []

    async def fake_post(path, *, params=None, payload):
        calls.append((path, params, payload))
        if path.endswith("set_session_info"):
            return {"errcode": 0, "errmsg": "ok"}
        assert path.endswith("get_pre_auth_code")
        assert params == {"suite_access_token": "suite-token"}
        return {"pre_auth_code": "pre-auth", "expires_in": 1200}

    monkeypatch.setattr(suite_env, "get_suite_access_token", fake_suite_token)
    monkeypatch.setattr(suite_env, "_post_json", fake_post)

    result = await suite_env.create_install_url(team_id=7, user_id=9)
    assert result["mode"] == "suite_install"
    assert result["auth_type"] == 1
    assert result["expires_in"] == 1200
    assert calls[1] == (
        "/cgi-bin/service/set_session_info",
        {"suite_access_token": "suite-token"},
        {"pre_auth_code": "pre-auth", "session_info": {"auth_type": 1}},
    )
    query = parse_qs(urlparse(result["install_url"]).query)
    assert query["suite_id"] == ["wwsuite123"]
    assert query["pre_auth_code"] == ["pre-auth"]
    assert query["redirect_uri"] == [
        "https://kellai.example.com/api/kellai/channels/wework/install/callback"
    ]
    assert suite_env.get_install_status(state=result["state"], team_id=7)["status"] == "pending"
    assert suite_env.get_install_status(state=result["state"], team_id=8)["expired"] is True
    session = suite_env._load_install_session(result["state"])
    assert 1195 <= int(session["expires_at"]) - int(time.time()) <= 1200


@pytest.mark.asyncio
async def test_create_auth_event_completes_only_pending_install(suite_env, monkeypatch):
    state = suite_env.create_install_session(team_id=7, user_id=9)
    calls = []

    async def fake_complete_install(*, state, auth_code):
        calls.append((state, auth_code))
        return {"authorized": True, "auth_corpid": "wwcorp123"}

    monkeypatch.setattr(suite_env, "complete_install", fake_complete_install)
    result = await suite_env.handle_suite_event(
        {"InfoType": "create_auth", "AuthCode": "temporary-auth-code"}
    )
    assert result == {
        "info_type": "create_auth",
        "authorized": True,
        "auth_corpid": "wwcorp123",
    }
    assert calls == [(state, "temporary-auth-code")]


@pytest.mark.asyncio
async def test_create_auth_uses_event_state_to_disambiguate(suite_env, monkeypatch):
    suite_env.create_install_session(team_id=7, user_id=9)
    selected = suite_env.create_install_session(team_id=8, user_id=10)
    calls = []

    async def fake_complete_install(*, state, auth_code):
        calls.append((state, auth_code))
        return {"authorized": True, "auth_corpid": "wwcorp123"}

    monkeypatch.setattr(suite_env, "complete_install", fake_complete_install)
    result = await suite_env.handle_suite_event(
        {
            "InfoType": "create_auth",
            "AuthCode": "temporary-auth-code",
            "State": selected,
        }
    )
    assert result["authorized"] is True
    assert calls == [(selected, "temporary-auth-code")]


@pytest.mark.asyncio
async def test_create_auth_accepts_recently_expired_pending_session(suite_env, monkeypatch):
    state = suite_env.create_install_session(team_id=7, user_id=9)
    with suite_env._conn() as conn:
        conn.execute(
            "UPDATE kellai_wework_install_sessions SET expires_at=? WHERE state=?",
            (int(time.time()) - 1, state),
        )
    calls = []

    async def fake_complete_install(*, state, auth_code):
        calls.append((state, auth_code))
        return {"authorized": True, "auth_corpid": "wwcorp123"}

    monkeypatch.setattr(suite_env, "complete_install", fake_complete_install)
    result = await suite_env.handle_suite_event(
        {"InfoType": "create_auth", "AuthCode": "temporary-auth-code"}
    )
    assert result["authorized"] is True
    assert calls == [(state, "temporary-auth-code")]


@pytest.mark.asyncio
async def test_complete_install_and_sync_external_customers(suite_env, monkeypatch):
    state = suite_env.create_install_session(team_id=7, user_id=9)
    with suite_env._conn() as conn:
        conn.execute(
            "UPDATE kellai_wework_install_sessions SET expires_at=? WHERE state=?",
            (int(time.time()) - 1, state),
        )

    async def fake_suite_token(*, force=False):
        return "suite-token"

    async def fake_post(path, *, params=None, payload):
        assert path.endswith("get_permanent_code")
        return {
            "permanent_code": "permanent-code",
            "auth_corp_info": {"corpid": "wwcorp123", "corp_name": "测试企业"},
            "auth_info": {"agent": [{"agentid": 1000002}]},
        }

    monkeypatch.setattr(suite_env, "get_suite_access_token", fake_suite_token)
    monkeypatch.setattr(suite_env, "_post_json", fake_post)
    completed = await suite_env.complete_install(state=state, auth_code="auth-code")
    assert completed["authorized"] is True
    assert suite_env.get_install_status(state=state, team_id=7)["corp_name"] == "测试企业"

    async def fake_corp_token(team_id):
        assert team_id == 7
        return "corp-token"

    async def fake_get(path, *, params):
        assert params["access_token"] == "corp-token"
        if path.endswith("get_follow_user_list"):
            return {"follow_user": ["zhangsan"]}
        if path.endswith("externalcontact/list"):
            return {"external_userid": ["wm_customer_1"], "next_cursor": ""}
        if path.endswith("externalcontact/get"):
            return {
                "external_contact": {
                    "external_userid": "wm_customer_1",
                    "name": "真实客户甲",
                    "avatar": "https://example.com/avatar.png",
                    "type": 1,
                    "gender": 1,
                },
                "follow_user": [{"userid": "zhangsan"}],
            }
        raise AssertionError(path)

    monkeypatch.setattr(suite_env, "get_corp_access_token", fake_corp_token)
    monkeypatch.setattr(suite_env, "_get_json", fake_get)
    result = await suite_env.sync_external_customers(7)
    assert result["synced"] == 1
    assert result["imported"] == 1
    assert result["customers"][0]["external_userid"] == "wm_customer_1"
    assert result["customers"][0]["name"] == "真实客户甲"


@pytest.mark.asyncio
async def test_acquisition_members_are_scoped_to_requested_team(suite_env, monkeypatch):
    token_calls = []

    async def fake_corp_token(team_id):
        token_calls.append(team_id)
        return f"corp-token-team-{team_id}"

    async def fake_get(path, *, params):
        assert params["access_token"] == "corp-token-team-7"
        if path.endswith("get_follow_user_list"):
            return {"follow_user": ["zhangsan"]}
        if path.endswith("user/get"):
            assert params["userid"] == "zhangsan"
            return {"userid": "zhangsan", "name": "张三"}
        raise AssertionError(path)

    monkeypatch.setattr(suite_env, "get_corp_access_token", fake_corp_token)
    monkeypatch.setattr(suite_env, "_get_json", fake_get)

    result = await suite_env.list_acquisition_members(7)

    assert token_calls == [7]
    assert result == {
        "members": [{"userid": "zhangsan", "name": "张三"}],
        "total": 1,
    }


@pytest.mark.asyncio
async def test_create_acquisition_link_is_team_scoped(suite_env, monkeypatch):
    token_calls = []
    api_calls = []

    async def fake_corp_token(team_id):
        token_calls.append(team_id)
        return f"corp-token-team-{team_id}"

    async def fake_post(path, *, params=None, payload):
        api_calls.append((path, params, payload))
        return {
            "errcode": 0,
            "errmsg": "ok",
            "link": {
                "link_id": "link-team-7",
                "link_name": "官网咨询",
                "url": "https://work.weixin.qq.com/ca/test-link",
                "create_time": 1784100000,
            },
        }

    monkeypatch.setattr(suite_env, "get_corp_access_token", fake_corp_token)
    monkeypatch.setattr(suite_env, "_post_json", fake_post)

    result = await suite_env.create_acquisition_link(
        7,
        link_name=" 官网咨询 ",
        userids=["zhangsan", "zhangsan", "lisi"],
    )

    assert token_calls == [7]
    assert api_calls == [
        (
            "/cgi-bin/externalcontact/customer_acquisition/create_link",
            {"access_token": "corp-token-team-7"},
            {
                "link_name": "官网咨询",
                "range": {"user_list": ["zhangsan", "lisi"]},
                "skip_verify": True,
                "mark_source": True,
            },
        )
    ]
    assert result["link"]["link_id"] == "link-team-7"
    assert result["userids"] == ["zhangsan", "lisi"]
