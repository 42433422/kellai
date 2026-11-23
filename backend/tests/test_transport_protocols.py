"""Actual provider request construction with HTTPX MockTransport only."""
import json
import logging
from urllib.parse import parse_qs

import httpx
import pytest

from app.channels import ChannelRegistry, config_store
from app.channels.http_client import BaseChannelClient, ChannelHTTPError, send_error
from app.services.tenant_context import tenant_scope
from app.main import _AccessPathOnly


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,config,host,path,response", [
    ("telegram", {"bot_token":"bot-secret"}, "api.telegram.org", "/botbot-secret/sendMessage", {"ok":True,"result":{"message_id":81}}),
    ("line", {"channel_access_token":"line-secret"}, "api.line.me", "/v2/bot/message/push", {"sentMessages":[{"id":"81"}]}),
    ("line", {"channel_access_token":"line-secret"}, "api.line.me", "/v2/bot/message/push", {"sentMessages":[{"id":81}]}),
    ("whatsapp", {"phone_number_id":"1234","access_token":"wa-secret"}, "graph.facebook.com", "/v25.0/1234/messages", {"messages":[{"id":"wamid.81"}]}),
])
async def test_official_text_senders_use_selected_credentials_and_one_post(tool_env, kind, config, host, path, response):
    calls=[]
    def provider(request):
        calls.append(request)
        assert request.method == "POST" and request.url.host == host and request.url.path == path
        assert "secret" not in request.content.decode()
        if kind != "telegram":
            assert request.headers["authorization"] == "Bearer " + config.get("access_token",config.get("channel_access_token"))
        return httpx.Response(200,json=response)
    with tenant_scope(1):
        config_store.create_connection(kind,config,connection_id="send")
        adapter=ChannelRegistry().get(kind,"send")
        with config_store.connection_scope("send"):
            original=await adapter._adapter._get_client()
            replacement=httpx.AsyncClient(base_url=original.base_url,headers=original.headers,transport=httpx.MockTransport(provider))
            await original.aclose()
            adapter._adapter._client=replacement
        result=await adapter.send_message("recipient","Hello")
        assert result["success"] and result["delivery_state"] == "accepted" and len(calls)==1


@pytest.mark.asyncio
async def test_twilio_credentials_and_form_and_aliyun_template_cannot_be_guessed(tool_env):
    calls=[]
    def twilio(request):
        calls.append(request)
        assert request.url.host == "api.twilio.com"
        assert parse_qs(request.content.decode()) == {"From":["+12025550100"],"To":["+12025550101"],"Body":["Hello"]}
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(201,json={"sid":"SM81","status":"queued"})
    with tenant_scope(1):
        config_store.create_connection("phone",{"provider":"twilio","account_sid":"ACtest","auth_token":"auth-secret","from_number":"+12025550100"},connection_id="twilio")
        adapter=ChannelRegistry().get("phone","twilio")
        adapter._adapter._client=httpx.AsyncClient(transport=httpx.MockTransport(twilio))
        assert (await adapter.send_message("+12025550101","Hello"))["message_id"] == "SM81"
        config_store.create_connection("phone",{"provider":"aliyun","access_key_id":"access-id","access_key_secret":"access-secret","sign_name":"approved","template_code":"SMS_123"},connection_id="ali")
        adapter=ChannelRegistry().get("phone","ali")
        def aliyun(request):
            calls.append(request)
            assert request.url.host == "dysmsapi.aliyuncs.com" and request.url.params["Signature"]
            assert json.loads(request.url.params["TemplateParam"]) == {"code":"1234"}
            return httpx.Response(200,json={"Code":"OK","BizId":"sms81"})
        adapter._adapter._client=httpx.AsyncClient(transport=httpx.MockTransport(aliyun))
        for kwargs in ({},{"template_param":"invalid"},{"template_param":{"code":1234}}):
            result=await adapter.send_message("13800138000","arbitrary text",**kwargs)
            assert result["definitely_not_sent"]
        assert len(calls)==1
        assert (await adapter.send_message("13800138000","",template_param={"code":"1234"}))["message_id"] == "sms81"
        assert len(calls)==2


@pytest.mark.asyncio
async def test_chatwoot_preflight_and_readback_bind_the_exact_inbox(tool_env):
    cfg={"base_url":"https://gateway.example","account_id":"7","inbox_id":"11","api_access_token":"secret","webhook_secret":"hook"}
    calls=[]
    def provider(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer secret"
        if request.method == "POST":
            payload=json.loads(request.content)
            assert payload["content_attributes"]["kellai_request_id"] == "request-81"
            assert payload["private"] is False and payload["message_type"] == "outgoing"
            return httpx.Response(200,json={"id":81,"inbox_id":11,"conversation_id":23})
        if request.url.path.endswith("/messages"):
            assert dict(request.url.params) == {"after":"81","before":"82"}
            return httpx.Response(200,json={"payload":[{"id":81,"inbox_id":11,"conversation_id":23,"message_type":1,"private":False,"status":"delivered"}]})
        return httpx.Response(200,json={"id":23,"inbox_id":11,"can_reply":True})
    with tenant_scope(1):
        config_store.create_connection("chatwoot",cfg,connection_id="chat")
        adapter=ChannelRegistry().get("chatwoot","chat")
        with config_store.connection_scope("chat"):
            original=await adapter._adapter._get_client()
            client=httpx.AsyncClient(base_url=original.base_url,headers=original.headers,transport=httpx.MockTransport(provider))
            await original.aclose(); adapter._adapter._client=client
            settings=adapter._adapter.settings()
        denied=await adapter.send_message("chatwoot:0000000000000000:7:11:23","no")
        assert denied["definitely_not_sent"] and not calls
        sent=await adapter.send_message(settings.target(23),"hello",idempotency_key="request-81")
        assert sent["message_id"] == "81" and sent["delivery_state"] == "accepted"
        with config_store.connection_scope("chat"):
            assert (await adapter._adapter.message_receipt(23,81))["status"] == "delivered"
        assert sum(request.method=="POST" for request in calls)==1


@pytest.mark.asyncio
async def test_timed_out_mutation_is_never_http_retried(tool_env):
    calls=[]
    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("URL containing secret must be hidden",request=request)
    client=BaseChannelClient()
    client._client=httpx.AsyncClient(base_url="https://api.example",transport=httpx.MockTransport(timeout))
    with pytest.raises(ChannelHTTPError) as caught:
        await client.post_json("/messages",json={"message":"approved"})
    assert caught.value.delivery_state == "unknown" and len(calls)==1
    assert "secret" not in str(caught.value)
    await client.close()


@pytest.mark.asyncio
async def test_secret_in_network_errors_and_provider_echo_is_never_exposed(tool_env, caplog):
    secret="NEVER-EXPOSE-ME"
    request=httpx.Request("POST",f"https://api.telegram.org/bot{secret}/sendMessage")
    assert secret not in json.dumps(send_error(httpx.HTTPStatusError(str(request.url),request=request,response=httpx.Response(500))))
    assert secret not in json.dumps(send_error(ValueError(secret)))
    with tenant_scope(1):
        config_store.create_connection("telegram",{"bot_token":secret},connection_id="tg")
        adapter=ChannelRegistry().get("telegram","tg")
        def reject(request):
            return httpx.Response(200,json={"ok":False,"error_code":400,"description":secret})
        adapter._adapter._client=httpx.AsyncClient(base_url="https://api.telegram.org",transport=httpx.MockTransport(reject))
        result=await adapter.send_message("recipient","text")
        assert secret not in json.dumps(result) and secret not in caplog.text
    record=logging.LogRecord("uvicorn.access",logging.INFO,"",1,'%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1","GET","/api/kellai/accounts/oauth/callback?code="+secret,"1.1",200),None)
    assert _AccessPathOnly().filter(record)
    assert secret not in record.getMessage() and "callback" in record.getMessage()


@pytest.mark.asyncio
async def test_legacy_wechat_oauth_metadata_is_not_remote_authentication(tool_env):
    with tenant_scope(1):
        config_store.create_connection("wechat",{"oauth_authorized":True,"oauth_openid":"old-openid"},connection_id="mp")
        assert (await ChannelRegistry().get("wechat","mp").test_connection())["connected"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{}, {"sentMessages": []}, {"sentMessages": [{}]},
                                      {"sentMessages": [{"id": True}]}, {"sentMessages": [{"id": " "}]}])
async def test_line_malformed_ack_stays_unknown_and_original_request_is_not_resent(tool_env, response):
    from app.channels.base import UnifiedMessage
    from app.services import outbound_delivery

    calls = []
    def provider(request):
        calls.append(request)
        return httpx.Response(200, json=response)
    with tenant_scope(1):
        config_store.create_connection("line", {"channel_access_token": "isolated-token"}, connection_id="line-ack")
        adapter = ChannelRegistry().get("line", "line-ack")
        adapter._adapter._client = httpx.AsyncClient(base_url="https://api.line.me", transport=httpx.MockTransport(provider))
        original = UnifiedMessage(id="", customer_id=7, connection_id="line-ack", channel_type="line",
            contact_id="recipient", contact_name="Recipient", direction="outbound", content="Approved text",
            metadata={"team_id": 1}, created_at="2026-11-23T00:00:00+00:00")
        async def send():
            return await adapter.send_message("recipient", original.content)
        first = await outbound_delivery.dispatch(original, idempotency_key="line-original", team_id=1, sender=send)
        again = await outbound_delivery.dispatch(original, idempotency_key="line-original", team_id=1, sender=send)
        assert first["status"] == again["status"] == "unknown"
        assert not first["success"] and first["provider_message_id"] == ""
        assert len(calls) == 1 and again["replayed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,config,response", [
    ("wechat", {"official_app_id": "wx-test", "official_app_secret": "wx-secret"}, {"errcode": 0}),
    ("wework", {"corp_id": "corp", "secret": "secret", "agent_id": "1001"}, {"errcode": 0, "msgid": "81"}),
    ("phone", {"provider": "twilio", "account_sid": "ACtest", "auth_token": "secret", "from_number": "+12025550100"}, {"sid": "SM81", "status": "queued"}),
])
async def test_sender_preserves_exact_approved_text(tool_env, monkeypatch, kind, config, response):
    from app.channels.base import UnifiedMessage
    from app.services import outbound_delivery, message_store

    approved = "  Approved text\n"
    sent = []
    async def provider(_transport, request):
        if request.method == "GET":
            return httpx.Response(200, json={"errcode": 0, "access_token": "isolated", "expires_in": 7200})
        sent.append(request)
        return httpx.Response(200, json=response)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", provider)
    with tenant_scope(1):
        config_store.create_connection(kind, config, connection_id="exact")
        adapter = ChannelRegistry().get(kind, "exact")
        original = UnifiedMessage(id="", customer_id=7, connection_id="exact", channel_type=kind,
            contact_id="recipient", contact_name="Recipient", direction="outbound", content=approved,
            metadata={"team_id": 1}, created_at="2026-11-23T00:00:00+00:00")
        result = await outbound_delivery.dispatch(original, idempotency_key="exact-request", team_id=1,
            sender=lambda: adapter.send_message(original.contact_id, original.content))
        assert result["success"] and len(sent) == 1
        remote_text = parse_qs(sent[0].content.decode())["Body"][0] if kind == "phone" else json.loads(sent[0].content)["text"]["content"]
        assert remote_text == approved
        assert message_store.get_messages(7, connection_id="exact")[0].content == remote_text
