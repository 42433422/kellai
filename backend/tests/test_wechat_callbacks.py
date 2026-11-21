from __future__ import annotations

import base64
import hashlib
import sqlite3
import struct
import time
import xml.etree.ElementTree as ET

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.wechat_callbacks import router
from app.channels import config_store
from app.services import auto_reply_runtime, growth_loop, llm_config, message_store, pipeline, wework_suite, workforce_routing
from app.services.tenant_context import tenant_scope


@pytest.fixture
def callback_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("KELLAI_CHANNEL_CONFIG_PATH", raising=False)
    monkeypatch.delenv("KELLAI_WECHAT_WEBHOOK_TEAM_ID", raising=False)
    monkeypatch.setenv("KELLAI_WECOM_SUITE_ID", "wwsuite123")
    monkeypatch.setenv("KELLAI_WECOM_SUITE_SECRET", "suite-secret")
    monkeypatch.setenv("KELLAI_WECOM_TOKEN", "callback-token")
    monkeypatch.setenv("KELLAI_WECOM_ENCODING_AES_KEY", "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG")
    monkeypatch.setattr(growth_loop, "resolve_customer_for_message", lambda _msg: pipeline.load_pipeline(7))
    monkeypatch.setattr(growth_loop, "apply_message_to_growth_loop", lambda _msg: {})
    monkeypatch.setattr(workforce_routing, "auto_assign_customer", lambda **_kw: None)
    monkeypatch.setattr(llm_config, "public_config", lambda: {"autoReplyEnabled": True, "autoReplyStages": ["connected"]})
    with tenant_scope(7):
        customer = pipeline.load_pipeline(7)
        customer.update(stage="connected", username="真实回调客户")
        pipeline.save_pipeline(customer)
        config_store.save("wechat", {"webhook_token": "tenant-seven-token", "official_original_id": "gh_team7"}, enabled=True)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tmp_path / "kellai.db"


def _xml(fields):
    root = ET.Element("xml")
    for key, value in fields.items():
        ET.SubElement(root, key).text = str(value)
    return ET.tostring(root, encoding="utf-8")


def _message(**changes):
    return {"ToUserName": "gh_team7", "FromUserName": "openid-seven", "CreateTime": str(int(time.time())),
            "MsgType": "text", "Content": "请问如何预约？", "MsgId": "7250000123456789001", **changes}


def _wechat_params(token="tenant-seven-token", timestamp=None, **changes):
    timestamp = str(timestamp if timestamp is not None else int(time.time()))
    nonce = "callback-nonce"
    return {"signature": hashlib.sha1("".join(sorted([token, timestamp, nonce])).encode()).hexdigest(),
            "timestamp": timestamp, "nonce": nonce, **changes}


def _authorize(db_path, *, team=7, corp="ww-team-seven", agent="100001", status="authorized"):
    wework_suite.ensure_schema()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO kellai_wework_authorizations "
                     "(team_id, auth_corpid, agent_id, permanent_code_enc, status, authorized_at, updated_at) "
                     "VALUES (?, ?, ?, '', ?, 'now', 'now')", (team, corp, agent, status))


def _wework_request(fields, *, outer=None):
    message = _xml(fields)
    key = base64.b64decode(wework_suite.suite_config()["encoding_aes_key"] + "=")
    plain = b"0123456789abcdef" + struct.pack("!I", len(message)) + message + b"wwsuite123"
    pad = 32 - len(plain) % 32
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    encrypted = base64.b64encode(encryptor.update(plain + bytes([pad]) * pad) + encryptor.finalize()).decode()
    timestamp, nonce = str(int(time.time())), "nonce-wework"
    params = {"timestamp": timestamp, "nonce": nonce,
              "msg_signature": wework_suite._signature("callback-token", timestamp, nonce, encrypted)}
    return params, _xml({"Encrypt": encrypted, **(outer or {})})


def test_wechat_scoped_challenge_and_missing_token_fail_closed(callback_env, monkeypatch):
    client, _ = callback_env
    response = client.get("/api/kellai/webhook/wechat/7", params=_wechat_params(echostr="verification-value"))
    assert response.status_code == 200 and response.text == "verification-value"
    monkeypatch.setenv("KELLAI_WECHAT_WEBHOOK_TOKEN", "tenant-seven-token")
    assert client.get("/api/kellai/webhook/wechat/8", params=_wechat_params(echostr="wrong-team")).status_code == 403
    with tenant_scope(7):
        config_store.save("wechat", {"webhook_token": ""})
    assert client.get("/api/kellai/webhook/wechat/7", params=_wechat_params(echostr="revoked")).status_code == 403


def test_wechat_legacy_url_requires_explicit_tenant_binding(callback_env, monkeypatch):
    client, _ = callback_env
    params = _wechat_params(echostr="bound")
    assert client.get("/api/kellai/webhook/wechat", params=params).status_code == 403
    monkeypatch.setenv("KELLAI_WECHAT_WEBHOOK_TEAM_ID", "7")
    assert client.get("/api/kellai/webhook/wechat", params=params).text == "bound"


@pytest.mark.parametrize("params", [
    {}, {"signature": "invalid", "timestamp": "1", "nonce": "x"},
    _wechat_params(timestamp=1), _wechat_params(token="another-team-token"),
])
def test_wechat_invalid_or_stale_signature_does_not_persist(callback_env, params):
    client, _ = callback_env
    assert client.post("/api/kellai/webhook/wechat/7", params=params, content=_xml(_message())).status_code == 403
    assert message_store.list_inbox(team_id=7, include_consumed=True) == []


def test_wechat_inbound_replay_is_one_inbox_message_and_one_job(callback_env):
    client, _ = callback_env
    # A team supplied by the external body is ignored; the URL+token own it.
    body = _xml(_message(team_id="88"))
    for _ in range(2):
        response = client.post("/api/kellai/webhook/wechat/7", params=_wechat_params(), content=body)
        assert response.status_code == 200 and response.text == "success"
    inbox = message_store.list_inbox("wechat", team_id=7, include_consumed=True)
    assert len(inbox) == 1 and inbox[0]["consumed"] == 1
    assert inbox[0]["metadata"]["team_id"] == 7
    assert len(message_store.get_messages(7, team_id=7)) == 1
    assert auto_reply_runtime.runtime_status(team_id=7)["counts"] == {"pending": 1}
    assert message_store.list_inbox(team_id=88, include_consumed=True) == []


def test_wechat_wrong_account_and_encrypted_mode_are_rejected(callback_env):
    client, _ = callback_env
    endpoint = "/api/kellai/webhook/wechat/7"
    assert client.post(endpoint, params=_wechat_params(), content=_xml(_message(ToUserName="gh_other"))).status_code == 403
    assert client.post(endpoint, params=_wechat_params(encrypt_type="aes"), content=_xml({"Encrypt": "ciphertext"})).status_code == 400
    assert client.post(endpoint, params=_wechat_params(), content=_xml({"Encrypt": "ciphertext"})).status_code == 400
    assert message_store.list_inbox(team_id=7, include_consumed=True) == []


def test_callback_malformed_duplicate_and_entity_xml_rejected(callback_env):
    client, _ = callback_env
    for body in (b"<xml>", b"<!DOCTYPE xml [<!ENTITY x 'hello'>]><xml>&x;</xml>",
                 "<!DOCTYPE xml [<!ENTITY x 'hello'>]><xml>&x;</xml>".encode("utf-16"),
                 b"<xml><MsgType>text</MsgType><MsgType>event</MsgType></xml>"):
        assert client.post("/api/kellai/webhook/wechat/7", params=_wechat_params(), content=body).status_code == 400


def test_inbox_failure_is_retryable_and_does_not_ack_success(callback_env, monkeypatch):
    client, _ = callback_env
    def fail(*_a, **_kw):
        raise sqlite3.OperationalError("disk temporarily unavailable")
    monkeypatch.setattr(message_store, "push_inbox", fail)
    assert client.post("/api/kellai/webhook/wechat/7", params=_wechat_params(), content=_xml(_message())).status_code == 503


def test_enqueue_failure_retains_inbox_and_replayed_callback_finishes(callback_env, monkeypatch):
    client, _ = callback_env
    original = auto_reply_runtime.enqueue_message
    def fail(_message):
        raise sqlite3.OperationalError("queue locked")
    monkeypatch.setattr(auto_reply_runtime, "enqueue_message", fail)
    body = _xml(_message())
    response = client.post("/api/kellai/webhook/wechat/7", params=_wechat_params(), content=body)
    assert response.status_code == 200
    assert message_store.list_inbox(team_id=7)[0]["consumed"] == 0
    monkeypatch.setattr(auto_reply_runtime, "enqueue_message", original)
    assert client.post("/api/kellai/webhook/wechat/7", params=_wechat_params(), content=body).status_code == 200
    assert message_store.list_inbox(team_id=7) == []
    assert len(message_store.get_messages(7, team_id=7)) == 1
    assert auto_reply_runtime.runtime_status(team_id=7)["counts"] == {"pending": 1}


def test_wework_verified_corp_authorization_owns_tenant_and_deduplicates(callback_env):
    client, db_path = callback_env
    _authorize(db_path)
    params, body = _wework_request(_message(ToUserName="ww-team-seven", AgentID="100001", team_id="88"),
                                  outer={"ToUserName": "untrusted-corp", "team_id": "88"})
    for _ in range(2):
        response = client.post("/api/kellai/webhook/wework", params=params, content=body)
        assert response.status_code == 200 and response.text == "success"
    inbox = message_store.list_inbox("wework", team_id=7, include_consumed=True)
    assert len(inbox) == 1 and inbox[0]["consumed"] == 1
    assert message_store.list_inbox(team_id=88, include_consumed=True) == []
    assert auto_reply_runtime.runtime_status(team_id=7)["counts"] == {"pending": 1}


@pytest.mark.parametrize("corp,status,agent", [("unknown-corp", "authorized", "100001"), ("ww-team-seven", "revoked", "100001"), ("ww-team-seven", "authorized", "100002")])
def test_wework_rejects_unknown_revoked_or_wrong_agent(callback_env, corp, status, agent):
    client, db_path = callback_env
    _authorize(db_path, status=status)
    params, body = _wework_request(_message(ToUserName=corp, AgentID=agent))
    assert client.post("/api/kellai/webhook/wework", params=params, content=body).status_code == 403
    assert message_store.list_inbox(team_id=7, include_consumed=True) == []


def test_wework_invalid_signature_cannot_select_tenant(callback_env):
    client, db_path = callback_env
    _authorize(db_path)
    params, body = _wework_request(_message(ToUserName="ww-team-seven", AgentID="100001"))
    params["msg_signature"] = "bad"
    assert client.post("/api/kellai/webhook/wework", params=params, content=body).status_code == 403
    assert message_store.list_inbox(team_id=7, include_consumed=True) == []


def test_wework_events_without_msgid_are_stable_and_not_auto_replied(callback_env):
    client, db_path = callback_env
    _authorize(db_path)
    fields = {"ToUserName": "ww-team-seven", "CreateTime": str(int(time.time())), "MsgType": "event", "Event": "change_external_contact", "ExternalUserID": "external-contact"}
    for _ in range(2):
        params, body = _wework_request(fields)
        assert client.post("/api/kellai/webhook/wework", params=params, content=body).status_code == 200
    inbox = message_store.list_inbox(team_id=7, include_consumed=True)
    assert len(inbox) == 1 and inbox[0]["content_type"] == "event"
    assert auto_reply_runtime.runtime_status(team_id=7)["counts"] == {}


def test_authorization_read_does_not_decrypt_and_enforces_context(callback_env, monkeypatch):
    _, db_path = callback_env
    _authorize(db_path)
    monkeypatch.setattr(wework_suite, "_decrypt", lambda _value: pytest.fail("identity lookup must not decrypt credentials"))
    assert wework_suite.load_authorization(7) == {"team_id": 7, "auth_corpid": "ww-team-seven", "agent_id": "100001", "status": "authorized"}
    with tenant_scope(8), pytest.raises(PermissionError):
        wework_suite.load_authorization(7)


@pytest.mark.parametrize("channel", ["wechat", "wework"])
def test_historical_callback_is_persisted_without_automatic_reply(callback_env, channel):
    client, db_path = callback_env
    # The transport signature is current and valid; the provider event itself
    # is historical. It remains visible without acquiring an automatic send.
    provider_time = "1577836800"
    fields = _message(CreateTime=provider_time)
    if channel == "wechat":
        endpoint = "/api/kellai/webhook/wechat/7"
        params, body = _wechat_params(), _xml(fields)
    else:
        _authorize(db_path)
        endpoint = "/api/kellai/webhook/wework"
        params, body = _wework_request({**fields, "ToUserName": "ww-team-seven", "AgentID": "100001"})
    response = client.post(endpoint, params=params, content=body)
    assert response.status_code == 200 and response.text == "success"
    inbox = message_store.list_inbox(channel, team_id=7, include_consumed=True)
    assert len(inbox) == 1 and inbox[0]["consumed"] == 1
    saved = message_store.get_messages(7, channel, team_id=7)
    assert len(saved) == 1 and saved[0].content == fields["Content"]
    assert saved[0].metadata["provider_created_at"] == provider_time
    assert auto_reply_runtime.runtime_status(team_id=7)["counts"] == {}
