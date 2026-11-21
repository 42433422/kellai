"""SMS form values must reach the selected provider without inventing template variables."""
from __future__ import annotations

import base64
import json
import os
from urllib.parse import parse_qs

import httpx
import pytest
import pytest_asyncio

os.environ.setdefault("KELLAI_APP_ENV", "development")
os.environ.setdefault("KELLAI_JWT_SECRET", "test-phone-configuration-only")
os.environ.setdefault("KELLAI_PASSWORD_SALT", "test-phone-configuration-only")

from app.channels import ChannelRegistry, config_store
from app.services.tenant_context import tenant_scope


@pytest_asyncio.fixture(autouse=True)
async def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KELLAI_CHANNEL_CONFIG_PATH", str(tmp_path / "channels.json"))
    for key in list(os.environ):
        if key == "KELLAI_CHANNEL_ENV_TEAM_ID" or key.startswith(("KELLAI_SMS_", "KELLAI_PHONE_")):
            monkeypatch.delenv(key)
    await ChannelRegistry().close_all()
    yield
    await ChannelRegistry().close_all()


async def save_form(config):
    from app.api.routes import ChannelConfigUpdate, update_channel_config
    response = await update_channel_config("phone", ChannelConfigUpdate(config=config, enabled=True))
    assert response["success"]
    return response["data"]


def catalog():
    return next(row for row in ChannelRegistry().list_channels() if row["channel_type"] == "phone")


@pytest.mark.asyncio
async def test_saved_twilio_form_reaches_http_with_tenant_credentials(monkeypatch):
    # The saved account, not a server-wide account or the first cached tenant, owns each send.
    monkeypatch.setenv("KELLAI_CHANNEL_ENV_TEAM_ID", "61")
    monkeypatch.setenv("KELLAI_SMS_ACCOUNT_SID", "AC-server")
    monkeypatch.setenv("KELLAI_SMS_AUTH_TOKEN", "server-token")
    monkeypatch.setenv("KELLAI_SMS_FROM_NUMBER", "+15559999999")
    captured = []

    def provider(request):
        captured.append(request)
        return httpx.Response(201, json={"sid": f"SM-{len(captured)}", "status": "queued"})

    for team in (61, 62):
        with tenant_scope(team):
            saved = await save_form({"provider": "twilio", "account_sid": f"AC-{team}",
                                     "auth_token": f"token-{team}", "from_number": f"+155500000{team}",
                                     "line": "line1"})
            assert saved["config"]["auth_token"] == config_store.REDACTED_VALUE
            assert not saved["onboarding"]["missing_required_fields"]
            assert "line" not in saved["onboarding"]["required_fields"]
            assert "line" not in catalog()["config_schema"]["properties"]
            assert catalog()["capabilities"]["message_types"] == ["text"]
            adapter = ChannelRegistry().get("phone")
            adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
            result = await adapter.send_message("+15551112222", "已确认的客户短信")
            assert result["success"] and result["delivery_state"] == "accepted"

    assert len(captured) == 2
    for team, request in zip((61, 62), captured):
        assert request.method == "POST"
        assert request.url.path == f"/2010-04-01/Accounts/AC-{team}/Messages.json"
        assert request.headers["authorization"] == "Basic " + base64.b64encode(f"AC-{team}:token-{team}".encode()).decode()
        assert parse_qs(request.content.decode()) == {
            "From": [f"+155500000{team}"], "To": ["+15551112222"], "Body": ["已确认的客户短信"]}


@pytest.mark.asyncio
async def test_provider_switch_keeps_masked_credentials_and_blocks_generic_text():
    from fastapi import HTTPException
    from app.services.messaging import _channel

    with tenant_scope(63):
        first = await save_form({"provider": "twilio", "account_sid": "AC-original",
                                 "auth_token": "original-token", "from_number": "+15550000001"})
        switched = await save_form({**first["config"], "provider": "aliyun",
                                    "access_key_id": "access-id", "access_key_secret": "access-secret",
                                    "sign_name": "客来来", "template_code": "SMS_12345"})
        profile = switched["onboarding"]
        assert not profile["missing_required_fields"]
        assert {"access_key_id", "access_key_secret", "sign_name", "template_code"} <= set(profile["required_fields"])
        assert "auth_token" not in profile["required_fields"]
        assert "模板发送界面尚未实现" in profile["next_action"]
        assert catalog()["capabilities"]["message_types"] == ["template"]
        assert catalog()["capabilities"]["send"] is True
        with pytest.raises(HTTPException) as error:
            _channel("phone")
        assert error.value.status_code == 409
        assert "模板" in str(error.value.detail)

        await save_form({**switched["config"], "provider": "twilio"})
        adapter = ChannelRegistry().get("phone")
        assert adapter._auth_token == "original-token"
        assert adapter._access_key_secret == "access-secret"
        assert catalog()["capabilities"]["message_types"] == ["text"]
        assert _channel("phone")[0] is adapter


def test_phone_guide_does_not_claim_authentication_is_delivery():
    from app.api.routes import _channel_onboarding_profile
    guide = _channel_onboarding_profile(
        "phone", {"account_sid": "AC-default", "auth_token": "token", "from_number": "+15550000001"},
        connected=True, enabled=True)
    assert not guide["missing_required_fields"]  # Twilio is the explicit schema/adapter default.
    assert guide["auth_modes"] == ["form"]
    assert guide["stages"][-1] == {"key": "verify_sms", "label": "真实短信验收", "status": "current"}
    assert "原生上行与送达回调尚未接通" in guide["next_action"]
    invalid = _channel_onboarding_profile("phone", {"provider": "line1"}, connected=False, enabled=True)
    assert "provider" in invalid["missing_required_fields"]


@pytest.mark.asyncio
async def test_aliyun_only_sends_explicit_valid_template_json():
    captured = []

    def provider(request):
        captured.append(request)
        return httpx.Response(200, json={"Code": "OK", "BizId": "provider-sms-id"})

    with tenant_scope(64):
        await save_form({"provider": "aliyun", "access_key_id": "access-id",
                         "access_key_secret": "access-secret", "sign_name": "客来来", "template_code": "SMS_12345"})
        adapter = ChannelRegistry().get("phone")
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
        for kwargs in ({}, {"template_param": "{'code':'123'}"}, {"template_param": ["123"]},
                       {"template_param": {"code": 123}}, {"template_param": "null"}):
            denied = await adapter.send_message("13800138000", "不能被猜成任意模板变量", **kwargs)
            assert denied["success"] is False and denied["definitely_not_sent"] is True
        assert not captured
        accepted = await adapter.send_message("13800138000", "", template_param={"name": "小C", "code": "123456"})
        assert accepted["success"] and accepted["message_id"] == "provider-sms-id"
        request = captured[0]
        assert request.url.host == "dysmsapi.aliyuncs.com"
        assert request.url.params["SignName"] == "客来来"
        assert request.url.params["TemplateCode"] == "SMS_12345"
        assert request.url.params["AccessKeyId"] == "access-id"
        assert request.url.params["Signature"]
        assert json.loads(request.url.params["TemplateParam"]) == {"name": "小C", "code": "123456"}
        assert "content" not in json.loads(request.url.params["TemplateParam"])
        # Constant approved templates have no variables, but {} still requires an explicit choice.
        assert (await adapter.send_message("13800138000", "", template_param="{}"))["success"]
        assert json.loads(captured[1].url.params["TemplateParam"]) == {}


@pytest.mark.asyncio
async def test_aliyun_missing_platform_id_remains_unknown():
    with tenant_scope(65):
        await save_form({"provider": "aliyun", "access_key_id": "access-id",
                         "access_key_secret": "access-secret", "sign_name": "客来来", "template_code": "SMS_12345"})
        adapter = ChannelRegistry().get("phone")
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"Code": "OK"})))
        result = await adapter.send_message("13800138000", "", template_param={})
        assert result["success"] is False and result["delivery_state"] == "unknown"
        assert not result.get("definitely_not_sent")
