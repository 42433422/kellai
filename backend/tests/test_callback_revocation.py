"""A callback authenticated before an account change cannot commit afterwards."""
import hashlib
import hmac
import json
import time

import httpx
import pytest

from app.api import channel_gateway
from app.channels import config_store
from app.main import app
from app.services import chatwoot_gateway, message_store
from app.services.tenant_context import tenant_scope
from tests.test_provider_callbacks import wecom_envelope


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["wechat", "wework"])
@pytest.mark.parametrize("change", ["disable", "replace"])
async def test_streaming_callback_rechecks_account_before_durable_write(tool_env, monkeypatch, kind, change):
    import base64
    key = bytes(range(32))
    cfg = ({"webhook_token": "mp-token", "official_original_id": "gh_one"} if kind == "wechat" else
           {"corp_id": "corp-one", "secret": "application-secret", "agent_id": "10001",
            "webhook_token": "callback-secret", "encoding_aes_key": base64.b64encode(key).decode().rstrip("=")})
    with tenant_scope(1):
        config_store.create_connection(kind, cfg, connection_id="callback-account")
    xml = ("<xml><ToUserName>gh_one</ToUserName><FromUserName>openid</FromUserName>"
           "<AgentID>10001</AgentID><MsgType>text</MsgType><MsgId>82</MsgId>"
           "<CreateTime>1760000000</CreateTime><Content>Original message</Content></xml>")
    if kind == "wechat":
        stamp, nonce = str(int(time.time())), "nonce"
        query = {"timestamp": stamp, "nonce": nonce,
                 "signature": hashlib.sha1("".join(sorted(["mp-token", stamp, nonce])).encode()).hexdigest()}
        raw = xml.encode()
    else:
        encrypted, query = wecom_envelope(xml.replace("gh_one", "corp-one").encode(), key)
        raw = ("<xml><Encrypt>" + encrypted + "</Encrypt></xml>").encode()
    original = channel_gateway._body

    async def change_while_receiving(request):
        body = await original(request)
        with tenant_scope(1):
            if change == "disable":
                config_store.update_connection("callback-account", enabled=False)
            else:
                config_store.update_connection("callback-account", {"webhook_token": "replacement-secret"})
        return body

    monkeypatch.setattr(channel_gateway, "_body", change_while_receiving)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://callback.example") as client:
        result = await client.post(f"/api/kellai/webhook/{kind}/1/callback-account", params=query, content=raw)
    assert result.status_code in {403, 409}, result.text
    with tenant_scope(1):
        assert message_store.list_inbox(connection_id="callback-account", include_consumed=True) == []
        assert message_store.list_contacts() == []


@pytest.mark.asyncio
async def test_verified_chatwoot_callback_cannot_commit_after_revocation(tool_env, monkeypatch):
    cfg = {"base_url": "https://chatwoot.example", "account_id": "7", "inbox_id": "11",
           "api_access_token": "account-token", "webhook_secret": "callback-secret"}
    with tenant_scope(1):
        config_store.create_connection("chatwoot", cfg, connection_id="callback-account")
    payload = {"event": "message_created", "id": 81, "content": "inbound", "private": False,
               "account": {"id": 7}, "inbox": {"id": 11}, "conversation": {"id": 23, "inbox_id": 11},
               "message_type": "incoming", "sender": {"id": 53, "name": "Known contact"}}
    raw = json.dumps(payload).encode()
    stamp = str(int(time.time()))
    headers = {"X-Chatwoot-Timestamp": stamp, "X-Chatwoot-Signature": "sha256=" + hmac.new(
        cfg["webhook_secret"].encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()}
    original = chatwoot_gateway.authenticate

    def revoke_after_auth(*args, **kwargs):
        result = original(*args, **kwargs)
        config_store.update_connection("callback-account", enabled=False)
        return result

    monkeypatch.setattr(chatwoot_gateway, "authenticate", revoke_after_auth)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://callback.example") as client:
        result = await client.post("/api/kellai/webhook/chatwoot/1/callback-account", content=raw, headers=headers)
    assert result.status_code in {403, 409}, result.text
    with tenant_scope(1):
        assert message_store.list_inbox(connection_id="callback-account", include_consumed=True) == []

