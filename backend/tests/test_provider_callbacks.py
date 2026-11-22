"""Signed, account-specific ingress using real cryptography and real SQLite."""
import base64
import hashlib
import hmac
import json
import struct
import time
from datetime import datetime, timezone

import httpx
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.main import app
from app.channels import ChannelRegistry, config_store
from app.services import message_store
from app.services.channel_ingest import sync_inbox
from app.services.tenant_context import tenant_scope


@pytest.mark.asyncio
async def test_chatwoot_signature_account_binding_and_consumed_deduplication(tool_env):
    cfg = {"base_url": "https://chatwoot.example", "account_id": "7", "inbox_id": "11",
           "api_access_token": "account-token", "webhook_secret": "first-secret"}
    with tenant_scope(1):
        config_store.create_connection("chatwoot", cfg, connection_id="first")
        config_store.create_connection("chatwoot", {**cfg, "webhook_secret": "second-secret"}, connection_id="second")
    payload = {"event": "message_created", "id": 81, "content": "inbound", "private": False,
               "account": {"id": 7}, "inbox": {"id": 11}, "conversation": {"id": 23, "inbox_id": 11},
               "message_type": "incoming", "sender": {"id": 53, "name": "Known contact"},
               "created_at": "2026-01-01T00:00:00Z"}
    raw = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    def headers(secret):
        return {"X-Chatwoot-Signature": "sha256=" + hmac.new(secret.encode(), timestamp.encode()+b"."+raw, hashlib.sha256).hexdigest(),
                "X-Chatwoot-Timestamp": timestamp}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("203.0.113.5", 80)),
                                base_url="https://callback.example") as client:
        bad = await client.post("/api/kellai/webhook/chatwoot/1/second", content=raw, headers=headers("first-secret"))
        assert bad.status_code == 401
        for cid, secret in (("first", "first-secret"), ("second", "second-secret"), ("first", "first-secret")):
            result = await client.post(f"/api/kellai/webhook/chatwoot/1/{cid}", content=raw, headers=headers(secret))
            assert result.status_code == 200, result.text
        assert (await client.post("/api/kellai/webhook/chatwoot/2/first", content=raw, headers=headers("first-secret"))).status_code == 403
    with tenant_scope(1):
        contacts = message_store.list_contacts()
        assert len(contacts) == 2
        for contact in contacts:
            rows = message_store.get_messages(contact["customer_id"], connection_id=contact["connection_id"])
            assert len(rows) == 1 and rows[0].content == "inbound"
            assert message_store.list_inbox(connection_id=contact["connection_id"]) == []
            inbox = message_store.list_inbox(connection_id=contact["connection_id"], include_consumed=True)
            assert len(inbox) == 1 and inbox[0]["consumed"] == 1


def wecom_envelope(xml, key, corp="corp-one", *, webhook_token="callback-secret"):
    plain = b"0123456789abcdef" + struct.pack("!I", len(xml)) + xml + corp.encode()
    padder = padding.PKCS7(256).padder()
    padded = padder.update(plain) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    encrypted = base64.b64encode(cipher.update(padded) + cipher.finalize()).decode()
    stamp, nonce = str(int(time.time())), "nonce"
    signature = hashlib.sha1("".join(sorted([webhook_token, stamp, nonce, encrypted])).encode()).hexdigest()
    return encrypted, {"msg_signature": signature, "timestamp": stamp, "nonce": nonce}


@pytest.mark.asyncio
async def test_self_built_wecom_aes_callback_checks_corp_agent_signature_and_dedupe(tool_env):
    key = bytes(range(32))
    cfg = {"corp_id": "corp-one", "secret": "application-secret", "agent_id": "10001",
           "webhook_token": "callback-secret", "encoding_aes_key": base64.b64encode(key).decode().rstrip("=")}
    with tenant_scope(1):
        config_store.create_connection("wework", cfg, connection_id="work")
    xml = b"<xml><ToUserName>corp-one</ToUserName><FromUserName>member</FromUserName><AgentID>10001</AgentID><MsgType>text</MsgType><MsgId>81</MsgId><CreateTime>1760000000</CreateTime><Content>Hello</Content></xml>"
    encrypted, query = wecom_envelope(xml, key)
    body = "<xml><Encrypt>" + encrypted + "</Encrypt></xml>"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://callback.example") as client:
        url = "/api/kellai/webhook/wework/1/work"
        assert (await client.post(url, params=query, content=body)).status_code == 200
        assert (await client.post(url, params=query, content=body)).status_code == 200
        assert (await client.post(url, params={**query, "msg_signature": "0"*40}, content=body)).status_code == 403
        wrong, wrong_query = wecom_envelope(xml, key, corp="other-corp")
        assert (await client.post(url, params=wrong_query, content="<xml><Encrypt>"+wrong+"</Encrypt></xml>")).status_code == 403
        wrong, wrong_query = wecom_envelope(xml.replace(b"10001", b"10002"), key)
        assert (await client.post(url, params=wrong_query, content="<xml><Encrypt>"+wrong+"</Encrypt></xml>")).status_code == 403
        assert (await client.post(url, params=query, content="not XML")).status_code == 400
        challenge, challenge_query = wecom_envelope(b"verified-echo", key)
        echo = await client.get(url, params={**challenge_query, "echostr": challenge})
        assert echo.status_code == 200 and echo.text == "verified-echo"
    with tenant_scope(1):
        contact = message_store.list_contacts()[0]
        assert len(message_store.get_messages(contact["customer_id"], connection_id="work")) == 1


@pytest.mark.asyncio
async def test_wechat_plaintext_callback_has_explicit_account_and_rejects_aes_claim(tool_env):
    with tenant_scope(1):
        config_store.create_connection("wechat", {"webhook_token": "mp-token", "official_original_id": "gh_one"}, connection_id="mp")
    stamp, nonce = str(int(time.time())), "nonce"
    signature = hashlib.sha1("".join(sorted(["mp-token", stamp, nonce])).encode()).hexdigest()
    query = {"timestamp": stamp, "nonce": nonce, "signature": signature}
    xml = "<xml><ToUserName>gh_one</ToUserName><FromUserName>openid</FromUserName><MsgType>text</MsgType><MsgId>82</MsgId><CreateTime>1760000000</CreateTime><Content>Hello</Content></xml>"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://callback.example") as client:
        path = "/api/kellai/webhook/wechat/1/mp"
        assert (await client.post(path, params=query, content=xml)).status_code == 200
        assert (await client.post(path, params=query, content=xml.replace("gh_one", "gh_wrong"))).status_code == 403
        assert (await client.post(path, params={**query, "encrypt_type": "aes"}, content=xml)).status_code == 400
        assert (await client.post(path, params={**query, "timestamp": "1"}, content=xml)).status_code == 403


@pytest.mark.asyncio
async def test_douyin_challenge_is_side_effect_free_and_messages_require_signature_and_owner(tool_env):
    token = {"open_id": "own", "access_token": "private-token", "scope": "enterprise.im",
             "expires_at": int(time.time())+3600}
    with tenant_scope(1):
        config_store.create_connection("douyin", {"client_key": "client", "client_secret": "secret",
            "oauth_token": token, "external_account_id": "own"}, connection_id="douyin")
    def signed(payload):
        raw = json.dumps(payload).encode()
        return raw, {"X-Douyin-Signature": hashlib.sha1(b"secret"+raw).hexdigest(), "Msg-Id": "provider-99"}
    payload = {"event": "receive_msg", "client_key": "client", "from_user_id": "visitor", "to_user_id": "own",
               "content": {"message_type": "text", "text": "Hello"}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://callback.example") as client:
        path = "/api/kellai/webhook/douyin/1/douyin"
        challenge = await client.post(path, json={"event": "verify_webhook", "client_key": "", "content": {"challenge": 12345}})
        assert challenge.status_code == 200 and challenge.json()["challenge"] == 12345
        assert (await client.post(path, json=payload)).status_code == 403
        raw, headers = signed({**payload, "to_user_id": "other-account"})
        assert (await client.post(path, content=raw, headers=headers)).status_code == 403
        raw, headers = signed(payload)
        assert (await client.post(path, content=raw, headers=headers)).status_code == 200
        assert (await client.post(path, content=raw, headers=headers)).status_code == 200
        raw, headers = signed({"event": "unauthorize", "client_key": "client", "from_user_id": "own", "content": {}})
        assert (await client.post(path, content=raw, headers=headers)).json()["data"]["revoked"] is True
    with tenant_scope(1):
        contact = message_store.list_contacts()[0]
        assert len(message_store.get_messages(contact["customer_id"], connection_id="douyin")) == 1
        item = config_store.get_connection("douyin", include_secrets=True)
        assert item["status"] == "requires_reconnect" and item["config"]["oauth_token"] == {}


@pytest.mark.asyncio
async def test_ingest_failure_replays_durably_without_second_message_or_business_send(tool_env, monkeypatch):
    with tenant_scope(1):
        config_store.create_connection("telegram", {"bot_token": "secret"}, connection_id="inbox")
        with config_store.connection_scope("inbox"):
            for mid in ("first", "second"):
                message_store.push_inbox("telegram", contact_id="visitor", direction="inbound", content=mid, msg_id=mid)
        original = message_store.save_message
        def failing(message):
            if message.id == "second":
                raise OSError("storage unavailable")
            return original(message)
        monkeypatch.setattr(message_store, "save_message", failing)
        with pytest.raises(OSError):
            await sync_inbox(connection_id="inbox")
        assert len(message_store.list_inbox(connection_id="inbox")) == 2
        monkeypatch.setattr(message_store, "save_message", original)
        result = await sync_inbox(connection_id="inbox")
        assert result["data"]["consumed"] == 2
        contact = message_store.list_contacts()[0]
        assert len(message_store.get_messages(contact["customer_id"], connection_id="inbox")) == 2
        assert message_store.list_inbox(connection_id="inbox") == []
