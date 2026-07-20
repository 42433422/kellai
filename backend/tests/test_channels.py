"""渠道适配器单元测试（不依赖真实凭据，全部 mock HTTP）。

覆盖：
- WeCom / WeChat / Douyin / Phone / MiniApp 五适配器
- 未配置时优雅返回未配置错误
- 配置存在时正确构造 HTTP 请求（mock httpx）
- 收件箱 → 拉取消息
- 联系人聚合

运行：
  cd backend && python3 -m pytest tests/test_channels.py -v
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 测试环境变量（必须在 import auth 之前）
os.environ.setdefault("KELLAI_APP_ENV", "development")
os.environ.setdefault("KELLAI_JWT_SECRET", "test-secret-for-pytest-only")
os.environ.setdefault("KELLAI_PASSWORD_SALT", "test-salt-for-pytest-only")

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

pytestmark = pytest.mark.asyncio

LLM_ENV_CANDIDATES = (
    "KELLAI_LLM_API_KEY",
    "VITE_KELLAI_LLM_API_KEY",
    "OPENAI_COMPATIBLE_API_KEY",
    "VITE_OPENAI_COMPATIBLE_API_KEY",
    "LLM_API_KEY",
    "VITE_LLM_API_KEY",
    "AI_API_KEY",
    "VITE_AI_API_KEY",
    "MODEL_API_KEY",
    "VITE_MODEL_API_KEY",
    "KELLAI_LLM_BASE_URL",
    "VITE_KELLAI_LLM_BASE_URL",
    "OPENAI_COMPATIBLE_BASE_URL",
    "VITE_OPENAI_COMPATIBLE_BASE_URL",
    "OPENAI_COMPATIBLE_API_BASE",
    "VITE_OPENAI_COMPATIBLE_API_BASE",
    "LLM_BASE_URL",
    "VITE_LLM_BASE_URL",
    "AI_BASE_URL",
    "VITE_AI_BASE_URL",
    "KELLAI_LLM_MODEL",
    "VITE_KELLAI_LLM_MODEL",
    "OPENAI_COMPATIBLE_MODEL",
    "VITE_OPENAI_COMPATIBLE_MODEL",
    "LLM_MODEL",
    "VITE_LLM_MODEL",
    "AI_MODEL",
    "VITE_AI_MODEL",
    "MODEL_NAME",
    "VITE_MODEL_NAME",
    "DEEPSEEK_API_KEY",
    "VITE_DEEPSEEK_API_KEY",
    "DEEPSEEK_KEY",
    "VITE_DEEPSEEK_KEY",
    "DEEPSEEK_BASE_URL",
    "VITE_DEEPSEEK_BASE_URL",
    "DEEPSEEK_API_BASE",
    "VITE_DEEPSEEK_API_BASE",
    "DEEPSEEK_API_URL",
    "VITE_DEEPSEEK_API_URL",
    "DEEPSEEK_MODEL",
    "VITE_DEEPSEEK_MODEL",
    "DEEPSEEK_LLM_MODEL",
    "VITE_DEEPSEEK_LLM_MODEL",
    "OPENAI_API_KEY",
    "VITE_OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "VITE_OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "VITE_OPENAI_API_BASE",
    "OPENAI_MODEL",
    "VITE_OPENAI_MODEL",
    "DASHSCOPE_API_KEY",
    "VITE_DASHSCOPE_API_KEY",
    "QWEN_API_KEY",
    "VITE_QWEN_API_KEY",
    "BAILIAN_API_KEY",
    "VITE_BAILIAN_API_KEY",
    "DASHSCOPE_BASE_URL",
    "VITE_DASHSCOPE_BASE_URL",
    "QWEN_BASE_URL",
    "VITE_QWEN_BASE_URL",
    "DASHSCOPE_API_BASE",
    "VITE_DASHSCOPE_API_BASE",
    "QWEN_API_BASE",
    "VITE_QWEN_API_BASE",
    "BAILIAN_BASE_URL",
    "VITE_BAILIAN_BASE_URL",
    "DASHSCOPE_MODEL",
    "VITE_DASHSCOPE_MODEL",
    "QWEN_MODEL",
    "VITE_QWEN_MODEL",
    "BAILIAN_MODEL",
    "VITE_BAILIAN_MODEL",
    "MOONSHOT_API_KEY",
    "VITE_MOONSHOT_API_KEY",
    "KIMI_API_KEY",
    "VITE_KIMI_API_KEY",
    "MOONSHOT_BASE_URL",
    "VITE_MOONSHOT_BASE_URL",
    "KIMI_BASE_URL",
    "VITE_KIMI_BASE_URL",
    "MOONSHOT_MODEL",
    "VITE_MOONSHOT_MODEL",
    "KIMI_MODEL",
    "VITE_KIMI_MODEL",
    "SILICONFLOW_API_KEY",
    "VITE_SILICONFLOW_API_KEY",
    "SILICON_FLOW_API_KEY",
    "VITE_SILICON_FLOW_API_KEY",
    "SILICONFLOW_BASE_URL",
    "VITE_SILICONFLOW_BASE_URL",
    "SILICON_FLOW_BASE_URL",
    "VITE_SILICON_FLOW_BASE_URL",
    "SILICONFLOW_MODEL",
    "VITE_SILICONFLOW_MODEL",
    "SILICON_FLOW_MODEL",
    "VITE_SILICON_FLOW_MODEL",
    "ARK_API_KEY",
    "VITE_ARK_API_KEY",
    "VOLCENGINE_ARK_API_KEY",
    "VITE_VOLCENGINE_ARK_API_KEY",
    "VOLCENGINE_API_KEY",
    "VITE_VOLCENGINE_API_KEY",
    "DOUBAO_API_KEY",
    "VITE_DOUBAO_API_KEY",
    "DOUBAO_ARK_API_KEY",
    "VITE_DOUBAO_ARK_API_KEY",
    "ARK_BASE_URL",
    "VITE_ARK_BASE_URL",
    "ARK_API_BASE",
    "VITE_ARK_API_BASE",
    "VOLCENGINE_ARK_BASE_URL",
    "VITE_VOLCENGINE_ARK_BASE_URL",
    "VOLCENGINE_ARK_API_BASE",
    "VITE_VOLCENGINE_ARK_API_BASE",
    "VOLCENGINE_BASE_URL",
    "VITE_VOLCENGINE_BASE_URL",
    "VOLCENGINE_API_BASE",
    "VITE_VOLCENGINE_API_BASE",
    "DOUBAO_BASE_URL",
    "VITE_DOUBAO_BASE_URL",
    "DOUBAO_API_BASE",
    "VITE_DOUBAO_API_BASE",
    "DOUBAO_ARK_BASE_URL",
    "VITE_DOUBAO_ARK_BASE_URL",
    "DOUBAO_ARK_API_BASE",
    "VITE_DOUBAO_ARK_API_BASE",
    "ARK_MODEL",
    "VITE_ARK_MODEL",
    "VOLCENGINE_ARK_MODEL",
    "VITE_VOLCENGINE_ARK_MODEL",
    "VOLCENGINE_MODEL",
    "VITE_VOLCENGINE_MODEL",
    "DOUBAO_MODEL",
    "VITE_DOUBAO_MODEL",
    "DOUBAO_ARK_MODEL",
    "VITE_DOUBAO_ARK_MODEL",
    "ZHIPU_API_KEY",
    "VITE_ZHIPU_API_KEY",
    "ZHIPUAI_API_KEY",
    "VITE_ZHIPUAI_API_KEY",
    "GLM_API_KEY",
    "VITE_GLM_API_KEY",
    "BIGMODEL_API_KEY",
    "VITE_BIGMODEL_API_KEY",
    "ZHIPU_BASE_URL",
    "VITE_ZHIPU_BASE_URL",
    "ZHIPU_API_BASE",
    "VITE_ZHIPU_API_BASE",
    "ZHIPUAI_BASE_URL",
    "VITE_ZHIPUAI_BASE_URL",
    "ZHIPUAI_API_BASE",
    "VITE_ZHIPUAI_API_BASE",
    "GLM_BASE_URL",
    "VITE_GLM_BASE_URL",
    "GLM_API_BASE",
    "VITE_GLM_API_BASE",
    "BIGMODEL_BASE_URL",
    "VITE_BIGMODEL_BASE_URL",
    "BIGMODEL_API_BASE",
    "VITE_BIGMODEL_API_BASE",
    "ZHIPU_MODEL",
    "VITE_ZHIPU_MODEL",
    "ZHIPUAI_MODEL",
    "VITE_ZHIPUAI_MODEL",
    "GLM_MODEL",
    "VITE_GLM_MODEL",
    "BIGMODEL_MODEL",
    "VITE_BIGMODEL_MODEL",
    "MINIMAX_API_KEY",
    "VITE_MINIMAX_API_KEY",
    "MINIMAX_GROUP_API_KEY",
    "VITE_MINIMAX_GROUP_API_KEY",
    "MINIMAX_BASE_URL",
    "VITE_MINIMAX_BASE_URL",
    "MINIMAX_API_BASE",
    "VITE_MINIMAX_API_BASE",
    "MINIMAX_MODEL",
    "VITE_MINIMAX_MODEL",
    "MIMO_API_KEY",
    "VITE_MIMO_API_KEY",
    "XIAOMI_MIMO_API_KEY",
    "VITE_XIAOMI_MIMO_API_KEY",
    "XIAOMIMIMO_API_KEY",
    "VITE_XIAOMIMIMO_API_KEY",
    "MI_MIMO_API_KEY",
    "VITE_MI_MIMO_API_KEY",
    "MIMO_BASE_URL",
    "VITE_MIMO_BASE_URL",
    "MIMO_API_BASE",
    "VITE_MIMO_API_BASE",
    "XIAOMI_MIMO_BASE_URL",
    "VITE_XIAOMI_MIMO_BASE_URL",
    "XIAOMI_MIMO_API_BASE",
    "VITE_XIAOMI_MIMO_API_BASE",
    "XIAOMIMIMO_BASE_URL",
    "VITE_XIAOMIMIMO_BASE_URL",
    "XIAOMIMIMO_API_BASE",
    "VITE_XIAOMIMIMO_API_BASE",
    "MIMO_TOKEN_PLAN_BASE_URL",
    "VITE_MIMO_TOKEN_PLAN_BASE_URL",
    "MIMO_TOKEN_PLAN_API_BASE",
    "VITE_MIMO_TOKEN_PLAN_API_BASE",
    "MIMO_MODEL",
    "VITE_MIMO_MODEL",
    "XIAOMI_MIMO_MODEL",
    "VITE_XIAOMI_MIMO_MODEL",
    "XIAOMIMIMO_MODEL",
    "VITE_XIAOMIMIMO_MODEL",
    "MI_MIMO_MODEL",
    "VITE_MI_MIMO_MODEL",
    "XAI_API_KEY",
    "VITE_XAI_API_KEY",
    "GROK_API_KEY",
    "VITE_GROK_API_KEY",
    "XAI_BASE_URL",
    "VITE_XAI_BASE_URL",
    "XAI_API_BASE",
    "VITE_XAI_API_BASE",
    "GROK_BASE_URL",
    "VITE_GROK_BASE_URL",
    "GROK_API_BASE",
    "VITE_GROK_API_BASE",
    "XAI_MODEL",
    "VITE_XAI_MODEL",
    "GROK_MODEL",
    "VITE_GROK_MODEL",
)


# ---------------------------------------------------------------------------
# 夹具：每个测试独立的临时 SQLite
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_channel_config(tmp_path, monkeypatch):
    """避免本机 data/channel_configs.json 影响通道单测。"""
    monkeypatch.setenv("KELLAI_CHANNEL_CONFIG_PATH", str(tmp_path / "channel_configs.json"))
    from app.channels import config_store

    importlib.reload(config_store)
    yield


@pytest.fixture(autouse=True)
def _isolate_channel_config(isolated_channel_config):
    yield


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))

    from app.services import crm_store, auth, message_store

    importlib.reload(crm_store)
    importlib.reload(auth)
    importlib.reload(message_store)
    yield tmp_path
    monkeypatch.undo()


# ---------------------------------------------------------------------------
# WeComAdapter
# ---------------------------------------------------------------------------


class TestWeComAdapter:
    async def test_unconfigured_returns_error(self):
        from app.channels.wecom import WeComAdapter

        a = WeComAdapter()
        out = await a.send_message("user_001", "hello")
        assert out["success"] is False
        assert "未配置" in out["error"]

        out = await a.test_connection()
        assert out["connected"] is False

    async def test_send_route_unconfigured_returns_before_persist(self, monkeypatch):
        from app.api.routes import ChannelSendMessageBody, send_message
        from app.services import message_store

        def fail_if_persisted(*_args, **_kwargs):
            raise AssertionError("unconfigured send must not write messages")

        monkeypatch.setattr(message_store, "save_message", fail_if_persisted)

        out = await send_message(
            ChannelSendMessageBody(
                customer_id=1,
                channel_type="wework",
                contact_id="@all",
                content="hello",
            )
        )

        assert out["success"] is False
        assert "未配置" in out["error"]
        assert out["data"]["message_id"] == ""

    async def test_bot_webhook_configured_test_ok(self, monkeypatch):
        from app.channels.wecom import WeComAdapter

        monkeypatch.setenv("KELLAI_WECOM_BOT_WEBHOOK", "https://example.com/bot/abc")
        a = WeComAdapter()
        out = await a.test_connection()
        assert out["connected"] is True
        assert "Webhook" in out["message"]

    async def test_customer_service_url_configured_test_ok(self):
        from app.channels import config_store
        from app.channels.wecom import WeComAdapter

        config_store.save(
            "wework",
            {"kf_url": "https://work.weixin.qq.com/kfid/kfcfd8a26b4a56f24ee"},
            enabled=True,
        )
        a = WeComAdapter()

        out = await a.test_connection()
        assert out["connected"] is True
        assert "open_kfid=kfcfd8a26b4a56f24ee" in out["message"]

        send = await a.send_message("user_001", "hello")
        assert send["success"] is False
        assert "API 发信还需" in send["error"]

    async def test_customer_entry_redirect_uses_saved_kf_url(self):
        from starlette.requests import Request

        from app.api import routes
        from app.channels import config_store

        config_store.save(
            "wework",
            {"kf_url": "https://work.weixin.qq.com/kfid/kfcfd8a26b4a56f24ee"},
            enabled=True,
        )
        req = Request(
            {
                "type": "http",
                "method": "GET",
                "scheme": "http",
                "path": "/api/kellai/channels/wework/customer-entry",
                "headers": [],
                "server": ("127.0.0.1", 8793),
                "client": ("127.0.0.1", 51234),
            }
        )

        payload = routes.wework_customer_entry(req, source="poster_001", mode="json")
        assert payload["success"] is True
        assert payload["data"]["entry_url"].endswith("source=poster_001")
        assert payload["data"]["target_url"] == "https://work.weixin.qq.com/kfid/kfcfd8a26b4a56f24ee"

        redirect = routes.wework_customer_entry(req, source="poster_001")
        assert redirect.status_code == 307
        assert redirect.headers["location"] == "https://work.weixin.qq.com/kfid/kfcfd8a26b4a56f24ee"

    async def test_bot_webhook_send(self, monkeypatch):
        from app.channels.wecom import WeComAdapter

        monkeypatch.setenv("KELLAI_WECOM_BOT_WEBHOOK", "https://example.com/bot/abc")
        a = WeComAdapter()

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"errcode": 0, "errmsg": "ok", "msgid": "msg-123"}

        fake_http = AsyncMock()
        fake_http.post = AsyncMock(return_value=fake_resp)
        fake_http.__aenter__ = AsyncMock(return_value=fake_http)
        fake_http.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=fake_http):
            out = await a.send_message("@chat", "hello world")
        assert out["success"] is True
        assert out["message_id"] == "msg-123"
        assert fake_http.post.await_args.args[0] == "https://example.com/bot/abc"
        body = fake_http.post.await_args.kwargs["json"]
        assert body["msgtype"] == "markdown"
        assert body["markdown"]["content"] == "hello world"

    async def test_app_message_send(self, monkeypatch):
        from app.channels.wecom import WeComAdapter, _WeComClient

        monkeypatch.setenv("KELLAI_WECOM_CORPID", "wxcorp123")
        monkeypatch.setenv("KELLAI_WECOM_CORPSECRET", "sec")
        monkeypatch.setenv("KELLAI_WECOM_AGENT_ID", "1000002")
        a = WeComAdapter()

        # 走真实 _WeComClient，但 mock 它内部的 post_with_token（避免嵌套 retry 链）
        send_body = {"errcode": 0, "errmsg": "ok", "msgid": "M-9"}

        async def fake_post_with_token(self, path, payload):
            return send_body

        with patch.object(_WeComClient, "post_with_token", fake_post_with_token):
            out = await a.send_message("user_001", "hi")
        assert out["success"] is True
        assert out["message_id"] == "M-9"


# ---------------------------------------------------------------------------
# WeChatAdapter（微信开放平台 / 公众号 / Webhook）
# ---------------------------------------------------------------------------


class TestWeChatAdapter:
    async def test_unconfigured_returns_error(self):
        from app.channels.wechat import WeChatAdapter

        a = WeChatAdapter()
        out = await a.send_message("u", "x")
        assert out["success"] is False
        assert "未配置" in out["error"]

    async def test_uses_wecom_webhook_when_configured(self, monkeypatch):
        from app.channels.wechat import WeChatAdapter

        monkeypatch.setenv("KELLAI_WECHAT_BOT_WEBHOOK", "https://example.com/bot/chat")

        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = {"errcode": 0, "msgid": "wm-1"}
        fake_http = AsyncMock()
        fake_http.post = AsyncMock(return_value=fake_resp)
        fake_http.__aenter__ = AsyncMock(return_value=fake_http)
        fake_http.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=fake_http):
            a = WeChatAdapter()
            out = await a.send_message("@chat", "ping")
        assert out["success"] is True
        assert out["message_id"] == "wm-1"

    async def test_oauth_authorized_config_marks_connected(self):
        from app.channels import config_store
        from app.channels.wechat import WeChatAdapter

        config_store.save(
            "wechat",
            {
                "app_id": "wx_open_app",
                "app_secret": "sec",
                "oauth_authorized": "true",
                "oauth_openid": "openid_123",
                "oauth_unionid": "union_123",
            },
            enabled=True,
            connected=True,
        )

        out = await WeChatAdapter().test_connection()
        assert out["connected"] is True
        assert "OAuth 已授权" in out["message"]

    async def test_customer_service_message_send(self):
        from app.channels import config_store
        from app.channels.wechat import WeChatAdapter, _WeChatOfficialClient

        config_store.save(
            "wechat",
            {
                "official_app_id": "wx_mp",
                "official_app_secret": "mp_sec",
            },
            enabled=True,
        )

        async def fake_post_with_token(self, path, payload):
            assert path == "/cgi-bin/message/custom/send"
            assert payload["touser"] == "openid_123"
            assert payload["msgtype"] == "text"
            assert payload["text"]["content"] == "你好"
            return {"errcode": 0, "errmsg": "ok", "msgid": "wx-msg-1"}

        with patch.object(_WeChatOfficialClient, "post_with_token", fake_post_with_token):
            out = await WeChatAdapter().send_message("openid_123", "你好")

        assert out["success"] is True
        assert out["message_id"] == "wx-msg-1"


# ---------------------------------------------------------------------------
# 渠道配置与别名
# ---------------------------------------------------------------------------


class TestChannelConfigStore:
    async def test_saved_config_is_read_and_merged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KELLAI_CHANNEL_CONFIG_PATH", str(tmp_path / "channels.json"))

        from app.channels import config_store

        importlib.reload(config_store)
        config_store.save(
            "wework",
            {
                "corp_id": "wxcorp123",
                "secret": "sec",
                "agent_id": "1000002",
                "kf_url": "https://work.weixin.qq.com/kfid/kfcfd8a26b4a56f24ee",
            },
            name="企业微信",
            enabled=True,
        )
        config_store.save("wework", {"oauth_authorized": "true"})

        assert config_store.get_field("wework", "corp_id") == "wxcorp123"
        assert config_store.get_field("wework", "secret") == "sec"
        assert config_store.get_field("wework", "oauth_authorized") == "true"

        all_config = config_store.get_all("wework")
        assert all_config["enabled"] is True
        assert all_config["config"]["agent_id"] == "1000002"
        assert all_config["config"]["oauth_authorized"] == "true"
        assert all_config["config"]["kf_url"].endswith("kfcfd8a26b4a56f24ee")

    async def test_wecom_env_alias_and_registry_alias(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KELLAI_CHANNEL_CONFIG_PATH", str(tmp_path / "channels.json"))
        monkeypatch.setenv("KELLAI_WECOM_CORP_ID", "env-corp")

        from app.channels import ChannelRegistry, config_store
        from app.channels.wecom import WeComAdapter

        importlib.reload(config_store)
        assert config_store.get_field("wework", "corp_id") == "env-corp"

        reg = ChannelRegistry()
        assert isinstance(reg.get("wecom"), WeComAdapter)
        assert reg.get("wecom") is reg.get("wework")

    async def test_channel_list_does_not_probe_external_connections(self, monkeypatch):
        from app.api.routes import list_channels
        from app.channels.wecom import WeComAdapter

        async def fail_if_called(self):
            raise AssertionError("list_channels must not call external connection tests")

        monkeypatch.setattr(WeComAdapter, "test_connection", fail_if_called)

        result = await list_channels()
        assert result["success"] is True
        wework = next(ch for ch in result["data"] if ch["type"] == "wework")
        assert wework["onboarding"]["recommended_mode"] == "scan"
        assert wework["onboarding"]["required_fields"] == []
        assert "corp_id" in wework["onboarding"]["optional_fields"]
        assert "测试连接" in {step["label"] for step in wework["onboarding"]["stages"]}
        douyin = next(ch for ch in result["data"] if ch["type"] == "douyin")
        assert douyin["onboarding"]["next_action"]
        assert douyin["onboarding"]["status"] in {"not_started", "saved", "connected"}

    async def test_wework_oauth_initiate_returns_official_embed_payload(self):
        from starlette.requests import Request

        from app.api.routes import (
            _wework_oauth_return_urls,
            _wework_oauth_states,
            wework_oauth_initiate,
        )
        from app.channels import config_store

        _wework_oauth_states.clear()
        _wework_oauth_return_urls.clear()
        config_store.save(
            "wework",
            {"corp_id": "wwcorp123", "secret": "sec", "agent_id": "1000002"},
            enabled=True,
        )
        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/api/kellai/channels/wework/oauth/initiate",
            "scheme": "http",
            "server": ("127.0.0.1", 8793),
            "client": ("127.0.0.1", 50000),
            "headers": [(b"host", b"127.0.0.1:8793"), (b"origin", b"http://127.0.0.1:5173")],
        })

        result = await wework_oauth_initiate(request)
        data = result["data"]

        assert data["embed_type"] == "ww_login"
        assert data["script_url"].endswith("wwLogin-1.2.7.js")
        assert data["ww_login"]["appid"] == "wwcorp123"
        assert data["ww_login"]["agentid"] == "1000002"
        assert "127.0.0.1%3A8793" in data["ww_login"]["redirect_uri"]
        assert data["state"] in _wework_oauth_states
        assert _wework_oauth_return_urls[data["state"]] == "http://127.0.0.1:5173/settings?tab=channels"

    async def test_wework_oauth_status_unknown_state_does_not_mark_authorized(self):
        import time

        from app.api.routes import _wework_oauth_states, wework_oauth_status

        _wework_oauth_states.clear()
        assert (await wework_oauth_status("missing"))["data"] == {"authorized": False, "expired": True}

        _wework_oauth_states["pending"] = time.time() + 60
        pending = (await wework_oauth_status("pending"))["data"]
        assert pending == {"authorized": False}


# ---------------------------------------------------------------------------
# DouyinAdapter
# ---------------------------------------------------------------------------


class TestDouyinAdapter:
    async def test_web_portal_contact_uses_desktop_sender(self, tmp_db):
        from app.channels.base import UnifiedMessage
        from app.channels.douyin import DouyinAdapter
        from app.services import douyin_desktop_automation, message_store

        message_store.save_message(
            UnifiedMessage(
                id="web-inbound-1",
                customer_id=88,
                channel_type="douyin",
                contact_id="customer-open-id",
                contact_name="真实客户",
                direction="inbound",
                content="你好",
                content_type="text",
                metadata={"source": "douyin_web_portal", "team_id": 7},
                created_at="2026-07-16T12:00:00+00:00",
            )
        )
        desktop_send = MagicMock(
            return_value={
                "success": True,
                "message_id": "",
                "source": "douyin_desktop_automation",
                "message_sent": True,
            }
        )
        with patch.object(
            douyin_desktop_automation,
            "automation_enabled",
            return_value=True,
        ), patch.object(
            douyin_desktop_automation,
            "send_message",
            desktop_send,
        ):
            result = await DouyinAdapter().send_message(
                "customer-open-id",
                "桌面回复",
                team_id=7,
                customer_id=88,
            )

        assert result["success"] is True
        desktop_send.assert_called_once_with(
            contact_name="真实客户",
            contact_id="customer-open-id",
            content="桌面回复",
        )

    async def test_unconfigured(self):
        from app.channels.douyin import DouyinAdapter

        a = DouyinAdapter()
        out = await a.send_message("open_x", "hello")
        assert out["success"] is False
        assert "未配置" in out["error"]
        out = await a.test_connection()
        assert out["connected"] is False

    async def test_authorized_enterprise_account_then_send(self, monkeypatch):
        from app.channels import douyin as douyin_module
        from app.channels.douyin import DouyinAdapter

        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_KEY", "ck")
        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_SECRET", "cs")
        a = DouyinAdapter()

        async def fake_access_context(team_id):
            assert team_id == 7
            return {"access_token": "ACT-1", "open_id": "owner-open-id"}

        send_resp = MagicMock(status_code=200)
        send_resp.json.return_value = {
            "data": {"error_code": 0, "server_msg_id": "DM-1"},
            "extra": {"error_code": 0},
        }
        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=send_resp)

        with patch.object(douyin_module, "access_context", fake_access_context), \
             patch.object(a, "_get_client", AsyncMock(return_value=fake_client)):
            out = await a.send_message("open_x", "hi", team_id=7)
        assert out["success"] is True
        assert out["message_id"] == "DM-1"
        assert fake_client.post.await_count == 1
        send_call = fake_client.post.await_args
        assert send_call.args[0] == "/enterprise/im/message/send/"
        assert send_call.kwargs["params"] == {
            "access_token": "ACT-1",
            "open_id": "owner-open-id",
        }
        assert send_call.kwargs["json"]["to_user_id"] == "open_x"
        assert send_call.kwargs["json"]["message_type"] == "text"
        assert json.loads(send_call.kwargs["json"]["content"]) == {"text": "hi"}

    async def test_saved_frontend_config_then_send(self, monkeypatch):
        from app.channels import config_store, douyin as douyin_module
        from app.channels.douyin import DouyinAdapter

        config_store.save("douyin", {"app_id": "ck", "app_secret": "cs"}, enabled=True)
        a = DouyinAdapter()

        async def fake_access_context(team_id):
            assert team_id == 8
            return {"access_token": "ACT-2", "open_id": "owner-2"}

        send_resp = MagicMock(status_code=200)
        send_resp.json.return_value = {
            "data": {"error_code": 0, "server_msg_id": "DM-2"},
            "extra": {"error_code": 0},
        }
        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=send_resp)

        with patch.object(douyin_module, "access_context", fake_access_context), \
             patch.object(a, "_get_client", AsyncMock(return_value=fake_client)):
            out = await a.send_message("open_x", "hi", team_id=8)

        assert out["success"] is True
        token_call = fake_client.post.await_args_list[0]
        assert token_call.kwargs["params"]["access_token"] == "ACT-2"

    async def test_miniapp_private_message_reply_uses_business_token(self, monkeypatch):
        from app.channels import douyin as douyin_module
        from app.channels.douyin import DouyinAdapter

        monkeypatch.setenv("KELLAI_DOUYIN_MINIAPP_APP_ID", "tt-miniapp")
        monkeypatch.setenv("KELLAI_DOUYIN_MINIAPP_SECRET", "webhook-secret")

        async def fake_business_token_context(**kwargs):
            assert kwargs == {
                "team_id": 7,
                "owner_open_id": "owner-open-id",
                "scope": "im.direct_message",
            }
            return {"business_token": "bus-token"}

        send_resp = MagicMock(status_code=200)
        send_resp.json.return_value = {
            "data": {"error_code": 0, "description": ""},
            "extra": {"error_code": 0, "description": ""},
            "msg_id": "miniapp-message-1",
        }
        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=send_resp)
        adapter = DouyinAdapter()
        reply_context = {
            "event": "im_receive_msg",
            "team_id": 7,
            "owner_open_id": "owner-open-id",
            "miniapp_app_id": "tt-miniapp",
            "conversation_id": "conversation-1",
            "server_message_id": "inbound-message-1",
        }

        with patch.object(
            douyin_module,
            "business_token_context",
            fake_business_token_context,
        ), patch.object(
            adapter,
            "_get_client",
            AsyncMock(return_value=fake_client),
        ):
            result = await adapter.send_message(
                "customer-open-id",
                "你好",
                team_id=7,
                customer_id=88,
                reply_context=reply_context,
            )

        assert result["success"] is True
        assert result["message_id"] == "miniapp-message-1"
        call = fake_client.post.await_args
        assert call.args[0] == "/im/send/msg/"
        assert call.kwargs["params"] == {"open_id": "owner-open-id"}
        assert call.kwargs["headers"]["access-token"] == "bus-token"
        assert call.kwargs["json"] == {
            "content": {"msg_type": 1, "text": {"text": "你好"}},
            "to_user_id": "customer-open-id",
            "msg_id": "inbound-message-1",
            "conversation_id": "conversation-1",
            "scene": "im_reply_msg",
        }

    async def test_remote_miniapp_reply_forwards_webhook_context(self, monkeypatch):
        from app.channels import douyin as douyin_module
        from app.channels.douyin import DouyinAdapter

        reply_context = {
            "event": "im_receive_msg",
            "team_id": 7,
            "owner_open_id": "owner-open-id",
            "miniapp_app_id": "tt-miniapp",
            "conversation_id": "conversation-1",
            "server_message_id": "inbound-message-1",
        }
        remote_send = AsyncMock(
            return_value={"success": True, "message_id": "remote-message-1", "error": ""}
        )
        with patch.object(douyin_module, "remote_bridge_enabled", return_value=True), \
             patch.object(douyin_module, "remote_send_message", remote_send):
            result = await DouyinAdapter().send_message(
                "customer-open-id",
                "远端回复",
                team_id=7,
                customer_id=88,
                reply_context=reply_context,
            )

        assert result["success"] is True
        remote_send.assert_awaited_once_with(
            team_id=7,
            contact_id="customer-open-id",
            content="远端回复",
            persona_id="",
            customer_id=88,
            reply_context=reply_context,
        )

    async def test_client_token_uses_official_grant_type(self, monkeypatch):
        from app.channels.douyin import DouyinAdapter

        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_KEY", "ck")
        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_SECRET", "cs")
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "data": {
                "access_token": "client-token",
                "expires_in": 7200,
                "error_code": 0,
            }
        }
        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=response)
        adapter = DouyinAdapter()
        with patch.object(adapter, "_get_client", AsyncMock(return_value=fake_client)):
            token, ttl = await adapter._fetch_client_token()
        assert (token, ttl) == ("client-token", 7200)
        assert fake_client.post.await_args.kwargs["json"]["grant_type"] == "client_credential"

    async def test_app_credentials_are_verified_before_authorization(self, tmp_db):
        from app.services import douyin_channel

        response = MagicMock(status_code=200)
        response.json.return_value = {
            "data": {
                "access_token": "client-token",
                "expires_in": 7200,
                "error_code": 0,
            }
        }
        fake_client = AsyncMock()
        fake_client.__aenter__.return_value = fake_client
        fake_client.__aexit__.return_value = False
        fake_client.post = AsyncMock(return_value=response)

        with patch.object(douyin_channel.httpx, "AsyncClient", return_value=fake_client):
            result = await douyin_channel.validate_app_credentials(
                next_client_key="real-client-key",
                next_client_secret="real-client-secret",
            )

        assert result["credentials_valid"] is True
        call = fake_client.post.await_args
        assert call.args[0].endswith("/oauth/client_token/")
        assert call.kwargs["json"] == {
            "client_key": "real-client-key",
            "client_secret": "real-client-secret",
            "grant_type": "client_credential",
        }

    async def test_miniapp_business_token_is_encrypted_and_cached(
        self,
        tmp_db,
        monkeypatch,
    ):
        from app.services import douyin_channel

        monkeypatch.setenv("KELLAI_DOUYIN_MINIAPP_APP_ID", "tt-miniapp")
        monkeypatch.setenv("KELLAI_DOUYIN_MINIAPP_SECRET", "webhook-secret")
        monkeypatch.setenv("KELLAI_DOUYIN_STORAGE_KEY", "storage-key")
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "biz_token": "business-token",
            "biz_expires_in": 2592000,
            "biz_refresh_token": "business-refresh-token",
            "biz_refresh_expires_in": 31536000,
        }
        fake_client = AsyncMock()
        fake_client.__aenter__.return_value = fake_client
        fake_client.__aexit__.return_value = False
        fake_client.post = AsyncMock(return_value=response)

        with patch.object(douyin_channel.httpx, "AsyncClient", return_value=fake_client):
            first = await douyin_channel.business_token_context(
                team_id=7,
                owner_open_id="owner-open-id",
            )
            second = await douyin_channel.business_token_context(
                team_id=7,
                owner_open_id="owner-open-id",
            )

        assert first["business_token"] == "business-token"
        assert second["business_token"] == "business-token"
        assert fake_client.post.await_count == 1
        call = fake_client.post.await_args
        assert call.args[0].endswith("/oauth/business_token/")
        assert call.kwargs["json"] == {
            "client_key": "tt-miniapp",
            "client_secret": "webhook-secret",
            "open_id": "owner-open-id",
            "scope": "im.direct_message",
        }
        with douyin_channel._conn() as conn:
            row = conn.execute(
                """
                SELECT token_enc, refresh_token_enc
                FROM kellai_douyin_business_tokens
                WHERE team_id = 7 AND open_id = 'owner-open-id'
                """
            ).fetchone()
        assert row["token_enc"] != "business-token"
        assert row["refresh_token_enc"] != "business-refresh-token"

    async def test_oauth_tokens_are_encrypted_and_team_scoped(self, tmp_db, monkeypatch):
        from app.services import douyin_channel

        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_KEY", "ck")
        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_SECRET", "cs")
        monkeypatch.setenv("KELLAI_DOUYIN_STORAGE_KEY", "storage-key")
        monkeypatch.setenv("KELLAI_PUBLIC_BASE_URL", "https://kellai.example")

        initiated = douyin_channel.create_oauth_url(team_id=11, user_id=22)
        assert initiated["url"].startswith("https://open.douyin.com/platform/oauth/connect/")
        assert initiated["scopes"] == ["trial.whitelist", "user_info"]
        assert initiated["callback_url"].endswith("/api/kellai/channels/douyin/oauth/callback")
        assert initiated["webhook_url"].endswith("/api/kellai/webhook/douyin")

        token_response = MagicMock(status_code=200)
        token_response.json.return_value = {
            "data": {
                "error_code": 0,
                "access_token": "user-access-token",
                "refresh_token": "user-refresh-token",
                "open_id": "owner-open-id",
                "scope": "user_info,im.direct_message",
                "expires_in": 1296000,
                "refresh_expires_in": 2592000,
            },
            "message": "success",
        }
        user_response = MagicMock(status_code=200)
        user_response.json.return_value = {
            "data": {
                "error_code": 0,
                "open_id": "owner-open-id",
                "nickname": "测试企业号",
                "avatar": "https://example/avatar.png",
            }
        }

        fake_client = AsyncMock()
        fake_client.__aenter__.return_value = fake_client
        fake_client.__aexit__.return_value = False
        fake_client.post = AsyncMock(return_value=token_response)
        fake_client.get = AsyncMock(return_value=user_response)

        with patch.object(douyin_channel.httpx, "AsyncClient", return_value=fake_client):
            completed = await douyin_channel.complete_oauth(
                state=initiated["state"],
                code="oauth-code",
            )
        assert completed["authorized"] is True
        assert completed["team_id"] == 11
        assert completed["nickname"] == "测试企业号"

        auth = douyin_channel.get_authorization(11, include_tokens=True)
        assert auth is not None
        assert auth["access_token"] == "user-access-token"
        assert auth["refresh_token"] == "user-refresh-token"
        with douyin_channel._conn() as conn:
            row = conn.execute(
                "SELECT access_token_enc, refresh_token_enc FROM kellai_douyin_authorizations WHERE team_id = 11"
            ).fetchone()
        assert row["access_token_enc"] != "user-access-token"
        assert row["refresh_token_enc"] != "user-refresh-token"
        status = douyin_channel.get_oauth_status(state=initiated["state"], team_id=11)
        assert status["authorized"] is True
        assert status["nickname"] == "测试企业号"

    async def test_remote_app_credentials_are_encrypted(self, tmp_db, monkeypatch):
        from app.services import douyin_channel

        for key in (
            "KELLAI_DOUYIN_CLIENT_KEY",
            "KELLAI_DOUYIN_CLIENT_SECRET",
            "KELLAI_DOUYIN_APP_ID",
            "KELLAI_DOUYIN_APP_SECRET",
            "KELLAI_DOUYIN_STORAGE_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("KELLAI_WECOM_BRIDGE_KEY", "shared-public-bridge-key")
        monkeypatch.setenv("KELLAI_PUBLIC_BASE_URL", "https://kellai.example")

        result = douyin_channel.save_app_config(
            next_client_key="remote-client-key",
            next_client_secret="remote-client-secret",
            next_miniapp_app_id="tt-miniapp",
            next_miniapp_secret="miniapp-webhook-secret",
        )
        assert result["configured"] is True
        assert douyin_channel.client_key() == "remote-client-key"
        assert douyin_channel.client_secret() == "remote-client-secret"
        assert douyin_channel.miniapp_app_id() == "tt-miniapp"
        assert douyin_channel.miniapp_secret() == "miniapp-webhook-secret"
        with douyin_channel._conn() as conn:
            row = conn.execute(
                """
                SELECT client_secret_enc, miniapp_secret_enc
                FROM kellai_douyin_app_config
                WHERE id = 1
                """
            ).fetchone()
        assert row["client_secret_enc"] != "remote-client-secret"
        assert row["miniapp_secret_enc"] != "miniapp-webhook-secret"

    async def test_douyin_remote_config_is_not_persisted_in_plaintext(self, monkeypatch):
        from app.api import routes
        from app.channels import config_store

        async def fake_remote_save(
            *,
            next_client_key,
            next_client_secret,
            next_miniapp_app_id="",
            next_miniapp_secret="",
        ):
            assert next_client_key == "client-key"
            assert next_client_secret == "client-secret"
            assert next_miniapp_app_id == ""
            assert next_miniapp_secret == ""
            return {
                "configured": True,
                "client_key": "client-key",
                "secret_configured": True,
                "miniapp_app_id": "",
                "miniapp_secret_configured": False,
            }

        with patch("app.services.douyin_channel.remote_bridge_enabled", return_value=True), \
             patch("app.services.douyin_channel.remote_save_app_config", fake_remote_save):
            result = await routes.update_channel_config(
                "douyin",
                routes.ChannelConfigUpdate(
                    config={"app_id": "client-key", "app_secret": "client-secret"},
                    enabled=True,
                ),
            )
        assert result["success"] is True
        saved = config_store.get("douyin")
        assert saved["config"]["app_id"] == "client-key"
        assert saved["config"]["app_secret"] == ""
        assert saved["config"]["remote_credentials_configured"] == "true"
        assert "client-secret" not in json.dumps(saved, ensure_ascii=False)

    async def test_channel_list_refreshes_remote_douyin_authorization(self):
        from starlette.requests import Request

        from app.api import routes
        from app.channels import config_store

        config_store.save(
            "douyin",
            {
                "app_id": "client-key",
                "app_secret": "",
                "remote_credentials_configured": "true",
            },
            enabled=True,
            connected=False,
        )
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/kellai/channels",
                "headers": [],
                "query_string": b"",
                "state": {"user": {"id": 22, "team_id": 11}},
            }
        )

        async def fake_remote_status(team_id):
            assert team_id == 11
            return {"connected": True, "message": "抖音企业号已授权：测试企业号"}

        with patch("app.services.douyin_channel.remote_bridge_enabled", return_value=True), \
             patch("app.services.douyin_channel.remote_connection_status", fake_remote_status):
            result = await routes.list_channels(request)

        douyin = next(row for row in result["data"] if row["type"] == "douyin")
        assert douyin["connected"] is True
        assert douyin["message"] == "抖音企业号已授权：测试企业号"
        assert config_store.get("douyin")["connected"] is True

    async def test_signed_webhook_queues_real_private_message(self, tmp_db, monkeypatch):
        import hashlib
        import json as json_module

        from fastapi import BackgroundTasks
        from starlette.requests import Request

        from app.api import routes
        from app.services import douyin_channel, message_store

        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_KEY", "ck")
        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_SECRET", "cs")
        monkeypatch.setenv("KELLAI_DOUYIN_STORAGE_KEY", "storage-key")
        with douyin_channel._conn() as conn:
            conn.execute(
                """
                INSERT INTO kellai_douyin_authorizations
                    (team_id, client_key, open_id, nickname, avatar, scope,
                     access_token_enc, refresh_token_enc, access_token_expires_at,
                     refresh_token_expires_at, updated_at)
                VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)
                """,
                (
                    11,
                    "ck",
                    "owner-open-id",
                    "测试企业号",
                    "user_info,im.direct_message",
                    douyin_channel._encrypt("access"),
                    douyin_channel._encrypt("refresh"),
                    4102444800,
                    4102444800,
                    "2026-07-16T00:00:00+00:00",
                ),
            )

        payload = {
            "event": "im_send_msg",
            "client_key": "ck",
            "from_user_id": "customer-open-id",
            "to_user_id": "owner-open-id",
            "content": json_module.dumps(
                {
                    "conversation_short_id": "conversation-1",
                    "server_message_id": "server-message-1",
                    "message_type": "text",
                    "text": "我想了解套餐和价格",
                    "user_infos": [
                        {"open_id": "customer-open-id", "nick_name": "抖音客户"},
                        {"open_id": "owner-open-id", "nick_name": "测试企业号"},
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        raw = json_module.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        signature = hashlib.sha1(b"cs" + raw).hexdigest()
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/kellai/webhook/douyin",
                "headers": [
                    (b"x-douyin-signature", signature.encode()),
                    (b"msg-id", b"delivery-1"),
                ],
                "query_string": b"",
                "scheme": "https",
                "server": ("kellai.example", 443),
                "client": ("127.0.0.1", 10000),
            },
            receive,
        )
        background = BackgroundTasks()
        sync_mock = AsyncMock(return_value={"success": True})
        with patch.object(routes, "sync_channel_inbox", sync_mock):
            result = await routes.douyin_webhook_receive(request, background)
            await background()

        assert result["success"] is True
        assert result["data"]["direction"] == "inbound"
        inbox = message_store.list_inbox("douyin", limit=10, team_id=11)
        assert len(inbox) == 1
        assert inbox[0]["contact_id"] == "customer-open-id"
        assert inbox[0]["contact_name"] == "抖音客户"
        assert inbox[0]["content"] == "我想了解套餐和价格"
        assert inbox[0]["metadata"]["team_id"] == 11
        sync_mock.assert_awaited_once()

    async def test_miniapp_customer_service_webhook_routes_to_bound_team(self, tmp_db, monkeypatch):
        import hashlib
        import json as json_module

        from fastapi import BackgroundTasks
        from starlette.requests import Request

        from app.api import routes
        from app.services import douyin_channel, message_store

        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_KEY", "website-client-key")
        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_SECRET", "website-client-secret")
        monkeypatch.setenv("KELLAI_DOUYIN_MINIAPP_APP_ID", "tt7e7708cae012a78501")
        monkeypatch.setenv("KELLAI_DOUYIN_MINIAPP_SECRET", "miniapp-secret")
        monkeypatch.setenv("KELLAI_DOUYIN_STORAGE_KEY", "storage-key")
        with douyin_channel._conn() as conn:
            conn.execute(
                """
                INSERT INTO kellai_douyin_authorizations
                    (team_id, client_key, open_id, nickname, avatar, scope,
                     access_token_enc, refresh_token_enc, access_token_expires_at,
                     refresh_token_expires_at, updated_at)
                VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)
                """,
                (
                    39,
                    "website-client-key",
                    "website-owner-open-id",
                    "测试企业号",
                    "trial.whitelist,user_info",
                    douyin_channel._encrypt("access"),
                    douyin_channel._encrypt("refresh"),
                    4102444800,
                    4102444800,
                    "2026-07-16T00:00:00+00:00",
                ),
            )

        payload = {
            "event": "customer_service_message",
            "app_id": "tt7e7708cae012a78501",
            "content": json_module.dumps(
                {
                    "server_message_id": "miniapp-message-1",
                    "c_open_id": "miniapp-customer-open-id",
                    "msg_type": "text",
                    "msg_content": {"text": "小程序里咨询客服"},
                    "user_infos": [
                        {"c_open_id": "miniapp-customer-open-id", "nick_name": "小程序客户"}
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        raw = json_module.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        signature = hashlib.sha1(b"miniapp-secret" + raw).hexdigest()
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/kellai/webhook/douyin",
                "headers": [(b"x-douyin-signature", signature.encode())],
                "query_string": b"",
                "scheme": "https",
                "server": ("kellai.example", 443),
                "client": ("127.0.0.1", 10000),
            },
            receive,
        )
        background = BackgroundTasks()
        sync_mock = AsyncMock(return_value={"success": True})
        with patch.object(routes, "sync_channel_inbox", sync_mock):
            result = await routes.douyin_webhook_receive(request, background)
            await background()

        assert result["success"] is True
        assert result["data"]["direction"] == "inbound"
        inbox = message_store.list_inbox("douyin", limit=10, team_id=39)
        assert len(inbox) == 1
        assert inbox[0]["contact_id"] == "miniapp-customer-open-id"
        assert inbox[0]["contact_name"] == "小程序客户"
        assert inbox[0]["content"] == "小程序里咨询客服"
        assert inbox[0]["metadata"]["team_id"] == 39
        assert inbox[0]["metadata"]["miniapp_app_id"] == "tt7e7708cae012a78501"
        sync_mock.assert_awaited_once()

    async def test_remote_inbox_is_acknowledged_only_after_team_delivery(self, tmp_db):
        from app.services import douyin_channel, message_store

        team_11_id = message_store.push_inbox(
            "douyin",
            contact_id="customer-11",
            contact_name="团队11客户",
            direction="inbound",
            content="团队11消息",
            metadata={"team_id": 11},
            msg_id="douyin:team-11-message",
        )
        team_12_id = message_store.push_inbox(
            "douyin",
            contact_id="customer-12",
            contact_name="团队12客户",
            direction="inbound",
            content="团队12消息",
            metadata={"team_id": 12},
            msg_id="douyin:team-12-message",
        )

        pulled = douyin_channel.pull_team_inbox(11, limit=10)
        assert [row["id"] for row in pulled] == [team_11_id]
        assert {row["id"] for row in message_store.list_inbox("douyin", limit=10, team_id=11)} == {
            team_11_id,
        }
        assert [row["id"] for row in message_store.list_inbox("douyin", limit=10, team_id=12)] == [team_12_id]

        assert douyin_channel.ack_team_inbox(12, [team_11_id]) == 0
        assert douyin_channel.ack_team_inbox(11, [team_11_id]) == 1
        assert [row["id"] for row in message_store.list_inbox("douyin", limit=10, team_id=12)] == [
            team_12_id
        ]

    async def test_group_webhook_is_aggregated_by_conversation(self, tmp_db, monkeypatch):
        import hashlib
        import json as json_module

        from fastapi import BackgroundTasks
        from starlette.requests import Request

        from app.api import routes
        from app.services import douyin_channel, message_store

        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_KEY", "ck")
        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_SECRET", "cs")
        monkeypatch.setenv("KELLAI_DOUYIN_STORAGE_KEY", "storage-key")
        with douyin_channel._conn() as conn:
            conn.execute(
                """
                INSERT INTO kellai_douyin_authorizations
                    (team_id, client_key, open_id, nickname, avatar, scope,
                     access_token_enc, refresh_token_enc, access_token_expires_at,
                     refresh_token_expires_at, updated_at)
                VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)
                """,
                (
                    11,
                    "ck",
                    "owner-open-id",
                    "测试企业号",
                    "user_info,im.direct_message,im.group_fans.create_list",
                    douyin_channel._encrypt("access"),
                    douyin_channel._encrypt("refresh"),
                    4102444800,
                    4102444800,
                    "2026-07-16T00:00:00+00:00",
                ),
            )

        group_id = "@group-conversation-1"
        payload = {
            "event": "im_group_receive_msg",
            "client_key": "ck",
            "from_user_id": "customer-open-id",
            "to_user_id": "owner-open-id",
            "content": json_module.dumps(
                {
                    "conversation_short_id": group_id,
                    "server_message_id": "group-message-1",
                    "conversation_type": 2,
                    "message_type": "text",
                    "text": "群里想了解套餐",
                    "group_info": {"group_name": "华东客户交流群"},
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        raw = json_module.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        signature = hashlib.sha1(b"cs" + raw).hexdigest()
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/kellai/webhook/douyin",
                "headers": [(b"x-douyin-signature", signature.encode())],
                "query_string": b"",
                "scheme": "https",
                "server": ("kellai.example", 443),
                "client": ("127.0.0.1", 10000),
            },
            receive,
        )
        with patch.object(routes, "sync_channel_inbox", AsyncMock(return_value={"success": True})):
            result = await routes.douyin_webhook_receive(request, BackgroundTasks())

        assert result["data"]["direction"] == "inbound"
        inbox = message_store.list_inbox("douyin", limit=10, team_id=11)
        assert inbox[0]["contact_id"] == f"group:{group_id}"
        assert inbox[0]["contact_name"] == "华东客户交流群"
        assert inbox[0]["metadata"]["is_group"] is True
        assert inbox[0]["content"] == "群里想了解套餐"


class TestWorkforceRouting:
    @staticmethod
    def _seed_team_members():
        from app.services import auth

        auth.ensure_auth_schema()
        now = "2026-07-16T00:00:00+00:00"
        with auth._conn() as conn:
            conn.execute(
                """
                INSERT INTO kellai_teams
                    (id, name, owner_id, invite_code, settings_json, created_at, updated_at)
                VALUES (1, '接待团队', 1, 'TEAM1', '{}', ?, ?)
                """,
                (now, now),
            )
            conn.executemany(
                """
                INSERT INTO kellai_users
                    (id, email, phone, password_hash, display_name, avatar_url,
                     team_id, role, is_active, token_version, created_at, updated_at)
                VALUES (?, ?, '', '', ?, '', 1, ?, 1, 0, ?, ?)
                """,
                [
                    (1, "owner@example.com", "主管", "owner", now, now),
                    (2, "sales-a@example.com", "销售A", "sales", now, now),
                    (3, "sales-b@example.com", "销售B", "sales", now, now),
                ],
            )

    async def test_idle_online_member_is_preferred_and_claim_is_atomic(self, tmp_db):
        from app.services import workforce_routing
        from app.services.pipeline import create_customer

        self._seed_team_members()
        workforce_routing.heartbeat(team_id=1, user_id=2, state="online")
        workforce_routing.heartbeat(team_id=1, user_id=3, state="online")

        first = create_customer({"name": "客户A", "team_id": 1})
        first["team_id"] = 1
        from app.services.pipeline import save_pipeline
        save_pipeline(first)
        workforce_routing.assign_customer(
            customer_id=int(first["customer_id"]),
            team_id=1,
            assignee_user_id=2,
            actor_user_id=1,
            source="manager",
        )

        second = create_customer({"name": "客户B"})
        second["team_id"] = 1
        save_pipeline(second)
        assignment = workforce_routing.auto_assign_customer(
            customer_id=int(second["customer_id"]),
            team_id=1,
        )
        assert assignment is not None
        assert assignment["assignee_user_id"] == 3
        assert assignment["source"] == "auto_route"

        with pytest.raises(workforce_routing.AssignmentConflict):
            workforce_routing.claim_customer(
                customer_id=int(second["customer_id"]),
                team_id=1,
                user_id=2,
            )
        assert workforce_routing.assignment_for_customer(
            int(second["customer_id"]), team_id=1
        )["assignee_user_id"] == 3

    async def test_inbound_message_auto_assigns_and_syncs_owner(self, tmp_db):
        from app.channels.base import UnifiedMessage
        from app.services import message_store, workforce_routing
        from app.services.pipeline import load_pipeline

        self._seed_team_members()
        workforce_routing.heartbeat(team_id=1, user_id=2, state="online")
        saved = message_store.save_message(
            UnifiedMessage(
                id="workforce-inbound-1",
                customer_id=0,
                channel_type="douyin",
                contact_id="customer-open-id",
                contact_name="自动分配客户",
                direction="inbound",
                content="我想了解价格",
                content_type="text",
                metadata={"team_id": 1, "source": "douyin_webhook"},
                created_at="2026-07-16T00:00:00+00:00",
            )
        )

        assignment = workforce_routing.assignment_for_customer(
            saved.customer_id, team_id=1
        )
        assert assignment is not None
        assert assignment["assignee_user_id"] == 2
        from app.services.tenant_context import tenant_scope

        with tenant_scope(1):
            doc = load_pipeline(saved.customer_id)
        assert doc["team_id"] == 1
        assert doc["owner"] == "销售A"

    async def test_douyin_unified_workspace_assignment_acceptance(
        self,
        tmp_db,
        monkeypatch,
    ):
        """私聊/群消息、空闲优先、管理改派与抢单锁必须形成同一闭环。"""
        import hashlib
        import json as json_module

        from fastapi import BackgroundTasks, HTTPException
        from starlette.requests import Request

        from app.api import routes
        from app.services import douyin_channel, message_store, workforce_routing
        from app.services.pipeline import create_customer, save_pipeline

        self._seed_team_members()
        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_KEY", "acceptance-client-key")
        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_SECRET", "acceptance-client-secret")
        monkeypatch.setenv("KELLAI_DOUYIN_STORAGE_KEY", "acceptance-storage-key")
        monkeypatch.delenv("KELLAI_DOUYIN_REMOTE_BASE_URL", raising=False)
        monkeypatch.delenv("KELLAI_DOUYIN_BRIDGE_SERVER", raising=False)

        with douyin_channel._conn() as conn:
            conn.execute(
                """
                INSERT INTO kellai_douyin_authorizations
                    (team_id, client_key, open_id, nickname, avatar, scope,
                     access_token_enc, refresh_token_enc, access_token_expires_at,
                     refresh_token_expires_at, updated_at)
                VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "acceptance-client-key",
                    "business-open-id",
                    "验收企业号",
                    "user_info,im.direct_message,im.group_fans.create_list",
                    douyin_channel._encrypt("access-token"),
                    douyin_channel._encrypt("refresh-token"),
                    4102444800,
                    4102444800,
                    "2026-07-16T00:00:00+00:00",
                ),
            )

        workforce_routing.heartbeat(team_id=1, user_id=2, state="online")
        workforce_routing.heartbeat(team_id=1, user_id=3, state="online")

        existing = create_customer({"name": "销售A现有客户", "team_id": 1})
        existing["team_id"] = 1
        save_pipeline(existing)
        workforce_routing.assign_customer(
            customer_id=int(existing["customer_id"]),
            team_id=1,
            assignee_user_id=2,
            actor_user_id=1,
            source="manager",
        )

        async def deliver(payload: dict[str, object]) -> None:
            raw = json_module.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            signature = hashlib.sha1(b"acceptance-client-secret" + raw).hexdigest()
            sent = False

            async def receive():
                nonlocal sent
                if sent:
                    return {"type": "http.disconnect"}
                sent = True
                return {"type": "http.request", "body": raw, "more_body": False}

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/api/kellai/webhook/douyin",
                    "headers": [(b"x-douyin-signature", signature.encode())],
                    "query_string": b"",
                    "scheme": "https",
                    "server": ("kellai.example", 443),
                    "client": ("127.0.0.1", 10000),
                },
                receive,
            )
            result = await routes.douyin_webhook_receive(request, BackgroundTasks())
            assert result["success"] is True
            assert result["data"]["direction"] == "inbound"

        await deliver(
            {
                "event": "im_receive_msg",
                "client_key": "acceptance-client-key",
                "from_user_id": "private-customer-open-id",
                "to_user_id": "business-open-id",
                "content": json_module.dumps(
                    {
                        "server_message_id": "acceptance-private-1",
                        "message_type": "text",
                        "text": "私聊咨询企业套餐",
                        "user_infos": [
                            {
                                "open_id": "private-customer-open-id",
                                "nick_name": "私聊客户",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
        )
        await deliver(
            {
                "event": "im_group_receive_msg",
                "client_key": "acceptance-client-key",
                "from_user_id": "group-member-open-id",
                "to_user_id": "business-open-id",
                "content": json_module.dumps(
                    {
                        "conversation_short_id": "@acceptance-group",
                        "server_message_id": "acceptance-group-1",
                        "conversation_type": 2,
                        "message_type": "text",
                        "text": "群里咨询部署周期",
                        "group_info": {"group_name": "抖音客户交流群"},
                        "user_infos": [
                            {
                                "open_id": "group-member-open-id",
                                "nick_name": "群成员",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
        )

        synced = await routes.sync_channel_inbox(
            routes.ChannelSyncInboxBody(channel_type="douyin", limit=20, team_id=1)
        )
        assert synced["data"]["synced"] == 2
        assert synced["data"]["consumed"] == 2
        saved = synced["data"]["messages"]
        private_message = next(
            row for row in saved if not bool(row["metadata"].get("is_group"))
        )
        group_message = next(
            row for row in saved if bool(row["metadata"].get("is_group"))
        )

        private_assignment = workforce_routing.assignment_for_customer(
            int(private_message["customer_id"]), team_id=1
        )
        group_assignment = workforce_routing.assignment_for_customer(
            int(group_message["customer_id"]), team_id=1
        )
        assert private_assignment is not None
        assert private_assignment["source"] == "douyin_inbound"
        assert group_assignment is not None
        assert group_assignment["source"] == "douyin_inbound"
        assert {
            private_assignment["assignee_user_id"],
            group_assignment["assignee_user_id"],
        } == {2, 3}
        assert group_message["contact_id"] == "group:@acceptance-group"
        assert group_message["contact_name"] == "抖音客户交流群"

        manager = {"id": 1, "team_id": 1, "role": "owner"}
        reassigned = routes.workforce_assign_customer(
            int(private_message["customer_id"]),
            routes.WorkforceAssignBody(assignee_user_id=2),
            manager,
        )
        assert reassigned["data"]["assignment"]["assignee_user_id"] == 2
        assert reassigned["data"]["assignment"]["source"] == "manager"

        with pytest.raises(HTTPException) as conflict:
            routes.workforce_claim_customer(
                int(private_message["customer_id"]),
                {"id": 3, "team_id": 1, "role": "sales"},
            )
        assert conflict.value.status_code == 409

        workspace_rows = message_store.get_messages_with_state(
            int(private_message["customer_id"]), team_id=1
        )
        assert workspace_rows[0]["content"] == "私聊咨询企业套餐"
        assert workspace_rows[0]["assignee_user_id"] == 2
        assert workspace_rows[0]["assignee_name"] == "销售A"
        assert workspace_rows[0]["assignment_status"] == "assigned"
        assert message_store.get_unread_count(
            int(private_message["customer_id"]), team_id=1
        ) == 1

        overview = workforce_routing.routing_overview(1)
        assert overview["online_count"] == 2
        assert overview["assigned_count"] == 3
        assert {row["availability"] for row in overview["presence"] if row["online"]} == {
            "busy"
        }


# ---------------------------------------------------------------------------
# PhoneAdapter
# ---------------------------------------------------------------------------


class TestPhoneAdapter:
    async def test_unconfigured(self, monkeypatch):
        monkeypatch.delenv("KELLAI_SMS_PROVIDER", raising=False)
        monkeypatch.delenv("KELLAI_SMS_ACCOUNT_SID", raising=False)
        from app.channels.phone import PhoneAdapter

        a = PhoneAdapter()
        out = await a.send_message("+8613800000000", "hi")
        assert out["success"] is False
        assert "未配置" in out["error"]
        out = await a.test_connection()
        assert out["connected"] is False

    async def test_twilio_send(self, monkeypatch):
        monkeypatch.setenv("KELLAI_SMS_PROVIDER", "twilio")
        monkeypatch.setenv("KELLAI_SMS_ACCOUNT_SID", "AC123")
        monkeypatch.setenv("KELLAI_SMS_AUTH_TOKEN", "tok")
        monkeypatch.setenv("KELLAI_SMS_FROM_NUMBER", "+15005550006")
        from app.channels.phone import PhoneAdapter

        a = PhoneAdapter()
        fake_resp = MagicMock(status_code=201)
        fake_resp.json.return_value = {"sid": "SM-XYZ"}
        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=fake_resp)
        with patch.object(a, "_get_client", AsyncMock(return_value=fake_client)):
            out = await a.send_message("+8613800000000", "hi")
        assert out["success"] is True
        assert out["message_id"] == "SM-XYZ"
        call = fake_client.post.await_args
        assert call.kwargs["auth"] == ("AC123", "tok")
        assert call.kwargs["data"]["To"] == "+8613800000000"
        assert call.kwargs["data"]["From"] == "+15005550006"

    async def test_aliyun_send_signs_request(self, monkeypatch):
        monkeypatch.setenv("KELLAI_SMS_PROVIDER", "aliyun")
        monkeypatch.setenv("KELLAI_SMS_ACCESS_KEY_ID", "akid")
        monkeypatch.setenv("KELLAI_SMS_ACCESS_KEY_SECRET", "aksec")
        monkeypatch.setenv("KELLAI_SMS_SIGN_NAME", "客来来")
        monkeypatch.setenv("KELLAI_SMS_TEMPLATE_CODE", "SMS_123")
        from app.channels.phone import PhoneAdapter

        a = PhoneAdapter()
        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = {"Code": "OK", "RequestId": "AL-1", "Message": "OK"}
        fake_client = AsyncMock()
        fake_client.get = AsyncMock(return_value=fake_resp)
        with patch.object(a, "_get_client", AsyncMock(return_value=fake_client)):
            out = await a.send_message("13800000000", "测试")
        assert out["success"] is True
        assert out["message_id"] == "AL-1"
        call = fake_client.get.await_args
        params = call.kwargs["params"]
        assert params["Action"] == "SendSms"
        assert params["PhoneNumbers"] == "13800000000"
        assert params["SignName"] == "客来来"
        assert params["Signature"]


# ---------------------------------------------------------------------------
# MiniAppAdapter
# ---------------------------------------------------------------------------


class TestMiniAppAdapter:
    async def test_unconfigured(self):
        from app.channels.miniapp import MiniAppAdapter

        a = MiniAppAdapter()
        out = await a.send_message("openid_x", "hi")
        assert out["success"] is False
        assert "未配置" in out["error"]

    async def test_token_then_send(self, monkeypatch):
        monkeypatch.setenv("KELLAI_MINIAPP_APPID", "wxapp")
        monkeypatch.setenv("KELLAI_MINIAPP_SECRET", "sec")
        monkeypatch.setenv("KELLAI_MINIAPP_TEMPLATE_ID", "TPL-1")
        from app.channels.miniapp import MiniAppAdapter

        a = MiniAppAdapter()
        token_resp = MagicMock(status_code=200)
        token_resp.json.return_value = {
            "errcode": 0,
            "errmsg": "ok",
            "access_token": "T-1",
            "expires_in": 7200,
        }
        send_resp = MagicMock(status_code=200)
        send_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
        fake_client = AsyncMock()
        fake_client.get = AsyncMock(return_value=token_resp)
        fake_client.post = AsyncMock(return_value=send_resp)
        with patch.object(a, "_get_client", AsyncMock(return_value=fake_client)):
            out = await a.send_message("openid_x", "hi")
        assert out["success"] is True
        send_call = fake_client.post.await_args
        assert "subscribe/send" in send_call.args[0]
        assert send_call.kwargs["json"]["touser"] == "openid_x"
        assert send_call.kwargs["json"]["template_id"] == "TPL-1"

    async def test_saved_frontend_config_then_send(self):
        from app.channels import config_store
        from app.channels.miniapp import MiniAppAdapter

        config_store.save(
            "miniprogram",
            {"app_id": "wxapp", "app_secret": "sec", "template_id": "TPL-2"},
            enabled=True,
        )
        a = MiniAppAdapter()
        token_resp = MagicMock(status_code=200)
        token_resp.json.return_value = {
            "errcode": 0,
            "errmsg": "ok",
            "access_token": "T-2",
            "expires_in": 7200,
        }
        send_resp = MagicMock(status_code=200)
        send_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
        fake_client = AsyncMock()
        fake_client.get = AsyncMock(return_value=token_resp)
        fake_client.post = AsyncMock(return_value=send_resp)

        with patch.object(a, "_get_client", AsyncMock(return_value=fake_client)):
            out = await a.send_message("openid_x", "hi")

        assert out["success"] is True
        token_call = fake_client.get.await_args
        assert token_call.kwargs["params"]["appid"] == "wxapp"
        send_call = fake_client.post.await_args
        assert send_call.kwargs["json"]["template_id"] == "TPL-2"


# ---------------------------------------------------------------------------
# 收件箱：适配器 receive_messages 必须能消费 push_inbox 写入
# ---------------------------------------------------------------------------


class TestInboxEndToEnd:
    async def test_wechat_xml_parser_extracts_nested_cdata(self):
        from app.api.routes import _parse_wecom_xml

        body = _parse_wecom_xml(
            """<xml>
            <ToUserName><![CDATA[gh_test]]></ToUserName>
            <FromUserName><![CDATA[openid_abc]]></FromUserName>
            <MsgType><![CDATA[text]]></MsgType>
            <Content><![CDATA[我想了解报价和演示]]></Content>
            <MsgId>1234567890123456</MsgId>
            </xml>"""
        )

        assert body["FromUserName"] == "openid_abc"
        assert body["MsgType"] == "text"
        assert body["Content"] == "我想了解报价和演示"

    async def test_wechat_qr_payload_parser_extracts_uuid(self):
        from app.api.routes import _extract_wechat_qr_payload

        payload = _extract_wechat_qr_payload(
            """
            <html><body>
            <img class="qrcode" src="/connect/qrcode/081aBcD_efg" />
            <script src="https://lp.open.weixin.qq.com/connect/l/qrconnect"></script>
            </body></html>
            """
        )

        assert payload["uuid"] == "081aBcD_efg"
        assert payload["qr_image_url"] == "https://open.weixin.qq.com/connect/qrcode/081aBcD_efg"
        assert payload["poll_base"] == "https://lp.open.weixin.qq.com/connect/l/qrconnect"

    async def test_inbox_push_then_receive(self, tmp_db):
        from app.services import message_store
        from app.channels.wecom import WeComAdapter

        # 直接写 2 条到 wecom 收件箱
        message_store.push_inbox(
            "wecom", contact_id="u1", direction="inbound",
            content="客户咨询价格", contact_name="张三",
        )
        message_store.push_inbox(
            "wecom", contact_id="u2", direction="inbound",
            content="想看 demo", contact_name="李四",
        )
        a = WeComAdapter()
        msgs = await a.receive_messages(limit=10)
        assert len(msgs) == 2
        assert msgs[0].channel_type == "wecom"
        assert {m.contact_id for m in msgs} == {"u1", "u2"}

    async def test_mark_consumed(self, tmp_db):
        from app.services import message_store
        from app.channels.phone import PhoneAdapter

        mid = message_store.push_inbox(
            "phone", contact_id="+86138000000000", direction="inbound",
            content="客服收到回呼", contact_name="客户",
        )
        a = PhoneAdapter()
        msgs = await a.receive_messages(limit=5)
        assert any(m.id == mid for m in msgs)
        message_store.mark_inbox_consumed([mid])
        msgs2 = await a.receive_messages(limit=5)
        assert not any(m.id == mid for m in msgs2)

    async def test_get_contacts_aggregates_inbox(self, tmp_db):
        from app.services import message_store
        from app.channels.douyin import DouyinAdapter

        for cid, name in [("dy_1", "抖音A"), ("dy_2", "抖音B"), ("dy_3", "抖音C")]:
            message_store.push_inbox(
                "douyin", contact_id=cid, contact_name=name,
                direction="inbound", content="hi",
            )
        a = DouyinAdapter()
        contacts = await a.get_contacts(limit=10)
        ids = {c["id"] for c in contacts}
        assert ids == {"dy_1", "dy_2", "dy_3"}

    async def test_sync_inbox_drives_customer_pipeline_loop(self, tmp_db):
        from app.api.routes import ChannelSyncInboxBody, sync_channel_inbox
        from app.services import message_store
        from app.services.ai_copilot import get_follow_up_reminders
        from app.services.pipeline import list_pipeline_client_summaries

        message_store.push_inbox(
            "wework",
            contact_id="wx_open_1",
            direction="inbound",
            content="你们这个多少钱？我想看 demo",
            contact_name="张三",
        )

        out = await sync_channel_inbox(ChannelSyncInboxBody(channel_type="wework", limit=10))

        assert out["success"] is True
        assert out["data"]["synced"] == 1
        customers = list_pipeline_client_summaries()
        customer = next(c for c in customers if c["display_name"] == "张三")
        assert customer["display_name"] == "张三"
        assert customer["stage"] == "intake"
        assert "wework" in customer["channel_sources"]
        assert customer["ai_score"] > 0

        rows = message_store.get_messages_with_state(customer["customer_id"], limit=5)
        assert rows[0]["customer_name"] == "张三"
        assert rows[0]["pending_follow_up"] is True
        assert "需求" in rows[0]["next_action"] or "报价" in rows[0]["next_action"]

        reminders = get_follow_up_reminders(hours_threshold=48)
        reminder = next(r for r in reminders if r["customer_id"] == customer["customer_id"])
        assert reminder["pending_follow_up"] is True

    async def test_remote_douyin_inbox_acks_after_local_persist(self, tmp_db):
        from starlette.requests import Request

        from app.api.routes import ChannelSyncInboxBody, sync_channel_inbox
        from app.channels.base import UnifiedMessage
        from app.services.pipeline import list_pipeline_client_summaries

        adapter = AsyncMock()
        adapter.receive_messages = AsyncMock(
            return_value=[
                UnifiedMessage(
                    id="douyin:remote-message-1",
                    customer_id=0,
                    channel_type="douyin",
                    contact_id="remote-customer",
                    contact_name="远端抖音客户",
                    direction="inbound",
                    content="我要了解价格",
                    content_type="text",
                    metadata={"team_id": 11},
                    created_at="2026-07-16T12:00:00+00:00",
                )
            ]
        )
        registry = MagicMock()
        registry.get.return_value = adapter
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/kellai/channels/sync-inbox",
                "headers": [],
                "query_string": b"",
                "state": {"user": {"id": 22, "team_id": 11}},
            }
        )
        ack = AsyncMock(return_value=1)

        with patch("app.channels.ChannelRegistry", return_value=registry), \
             patch("app.services.douyin_channel.remote_bridge_enabled", return_value=True), \
             patch("app.services.douyin_channel.remote_ack_inbox", ack):
            out = await sync_channel_inbox(
                ChannelSyncInboxBody(channel_type="douyin", limit=10),
                request,
            )

        assert out["success"] is True
        assert out["data"]["synced"] == 1
        assert out["data"]["consumed"] == 1
        ack.assert_awaited_once_with(11, ["douyin:remote-message-1"])
        from app.services.tenant_context import tenant_scope

        with tenant_scope(11):
            customer = next(
                row
                for row in list_pipeline_client_summaries()
                if row["display_name"] == "远端抖音客户"
            )
        assert customer["team_id"] == 11

    async def test_simulate_customer_behavior_returns_scenario_assertions(self, tmp_db):
        from app.api.routes import SimulateCustomerBehaviorBody, simulate_customer_behavior
        from app.services.pipeline import list_pipeline_client_summaries

        out = await simulate_customer_behavior(SimulateCustomerBehaviorBody(count=5))

        assert out["success"] is True
        data = out["data"]
        assert data["created"] == 5
        assert data["summary"]["total"] == 5
        assert data["summary"]["synced"] >= 5
        assert len(data["scenario_results"]) == 5
        assert data["passed"] is True
        assert all(item["customer_id"] > 0 for item in data["scenario_results"])
        assert all(item["next_action"] for item in data["scenario_results"])

        simulated_ids = {int(item["customer_id"]) for item in data["scenario_results"]}
        business_ids = {int(item["customer_id"]) for item in list_pipeline_client_summaries()}
        all_rows = list_pipeline_client_summaries(include_demo=True)
        demo_rows = [item for item in all_rows if int(item["customer_id"]) in simulated_ids]
        assert simulated_ids.isdisjoint(business_ids)
        assert len(demo_rows) == len(simulated_ids)
        assert all(item["is_demo"] is True for item in demo_rows)

    async def test_llm_full_flow_simulation_uses_llm_and_reaches_signed(self, tmp_db, monkeypatch):
        from app.services import ai_copilot
        from app.services.llm_customer_simulator import run_llm_full_flow_simulation

        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        customer_turns = iter([
            "你们这个怎么收费？我想看 demo，也想把抖音和企微线索都接起来",
            "我们有3个门店、2个抖音号，每天大概80条消息，预算希望别太高",
            "报价有点贵，首月能不能给优惠？",
            "可以，那合同怎么签？如果今天付款多久上线？",
            "合同确认了，我已经付款了，发我交付清单吧",
        ])
        used_customer_llm = {"count": 0}

        def fake_call_llm(prompt: str, system_prompt: str = "", max_tokens: int = 1024) -> str:
            if "扮演一个真实中小商家客户" in system_prompt:
                used_customer_llm["count"] += 1
                return '{"message": "%s", "intent": "推进成交", "should_continue": true}' % next(customer_turns)
            if "意图分类器" in system_prompt:
                if "优惠" in prompt or "贵" in prompt:
                    return '{"intent": "negotiation", "confidence": 0.9, "keywords": ["优惠"]}'
                if "付款" in prompt or "合同" in prompt:
                    return '{"intent": "confirm", "confidence": 0.9, "keywords": ["付款"]}'
                return '{"intent": "inquiry", "confidence": 0.9, "keywords": ["收费"]}'
            if "客来来的销售跟单助手" in system_prompt:
                if "每天大概80条" in prompt:
                    return "需求已清楚，我给你一版方案和报价，覆盖抖音、企微和小程序。"
                if "首月" in prompt or "贵" in prompt:
                    return "可以申请首月优惠，确认后我发合同和付款信息。"
                if "合同" in prompt or "付款" in prompt:
                    return "收到付款确认，我发你交付清单并安排上线培训。"
                return "收到，我先了解你的需求，再给你方案。"
            if "回复草稿" in system_prompt:
                if "每天大概80条" in prompt:
                    return "需求已清楚，我给你一版方案和报价，覆盖抖音、企微和小程序。"
                if "首月" in prompt:
                    return "可以申请首月优惠，确认后我发合同和付款信息。"
                if "已经付款" in prompt:
                    return "收到付款确认，我发你交付清单并安排上线培训。"
                return "收到，我先了解你的需求，再给你方案。"
            return '{"intent": "interest", "confidence": 0.8, "keywords": ["方案"]}'

        monkeypatch.setattr(ai_copilot, "_call_llm", fake_call_llm)

        out = await run_llm_full_flow_simulation(
            turns=5,
            target_stage="signed",
            channel_type="douyin",
            use_llm=True,
            auto_reply=True,
        )

        assert used_customer_llm["count"] > 0
        assert out["llm_used"] is True
        assert out["mode"] == "llm"
        assert out["llm_agent_turns"] > 0
        assert out["passed"] is True
        assert out["final_stage"] == "signed"
        assert out["customer_id"] > 0
        assert any(e["direction"] == "inbound" for e in out["events"])
        assert any(e["direction"] == "outbound" for e in out["events"])
        assert all(item["passed"] for item in out["assertions"] if item["required"])

    async def test_full_flow_simulation_requires_real_llm_by_default(self, tmp_db, monkeypatch):
        from app.services.llm_customer_simulator import run_llm_full_flow_simulation

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        out = await run_llm_full_flow_simulation(
            turns=5,
            target_stage="signed",
            channel_type="douyin",
            use_llm=True,
            auto_reply=True,
        )

        assert out["llm_ready"] is False
        assert out["mode"] == "llm_required_not_ready"
        assert out["passed"] is False
        assert out["customer_id"] == 0
        assert "未配置真实 LLM" in out["failure_reason"]

    async def test_full_flow_simulation_dev_fallback_still_available(self, tmp_db, monkeypatch):
        from app.services.llm_customer_simulator import run_llm_full_flow_simulation

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        out = await run_llm_full_flow_simulation(
            turns=5,
            target_stage="signed",
            channel_type="douyin",
            use_llm=True,
            auto_reply=True,
            require_llm=False,
        )

        assert out["mode"] == "scripted_fallback"
        assert out["passed"] is True
        assert out["final_stage"] == "signed"

    async def test_llm_config_reads_openai_compatible_env_file(self, tmp_db, tmp_path, monkeypatch):
        from app.services import llm_config

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "KELLAI_LLM_API_KEY=test-compatible-key",
                    "KELLAI_LLM_BASE_URL=https://llm.example.test/v1",
                    "KELLAI_LLM_MODEL=compatible-model",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("KELLAI_ENV_FILE", str(env_file))
        llm_config._read_dotenv.cache_clear()

        cfg = llm_config.effective_config()

        assert cfg["provider"] == "custom"
        assert cfg["source"] == "KELLAI_LLM_API_KEY"
        assert cfg["base_url"] == "https://llm.example.test/v1"
        assert cfg["model"] == "compatible-model"

    async def test_llm_config_reads_desktop_vite_env_file(self, tmp_db, tmp_path, monkeypatch):
        from app.services import llm_config

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        desktop_dir = tmp_path / "desktop"
        desktop_dir.mkdir()
        (desktop_dir / ".env").write_text(
            "\n".join(
                [
                    "VITE_DEEPSEEK_API_KEY=desktop-vite-key",
                    "VITE_DEEPSEEK_BASE_URL=https://deepseek.desktop.test/v1",
                    "VITE_DEEPSEEK_MODEL=deepseek-desktop-model",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(llm_config, "_project_root", lambda: tmp_path)
        monkeypatch.delenv("KELLAI_ENV_FILE", raising=False)
        llm_config._read_dotenv.cache_clear()

        cfg = llm_config.effective_config()

        assert cfg["provider"] == "deepseek"
        assert cfg["source"] == "VITE_DEEPSEEK_API_KEY"
        assert cfg["base_url"] == "https://deepseek.desktop.test/v1"
        assert cfg["model"] == "deepseek-desktop-model"

    async def test_llm_config_reads_desktop_production_env_file(self, tmp_db, tmp_path, monkeypatch):
        from app.services import llm_config

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        desktop_dir = tmp_path / "desktop"
        desktop_dir.mkdir()
        (desktop_dir / ".env.production").write_text(
            "\n".join(
                [
                    "VITE_LLM_API_KEY=desktop-prod-compatible-key",
                    "VITE_LLM_BASE_URL=https://desktop-prod.example.test/v1",
                    "VITE_LLM_MODEL=desktop-prod-model",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(llm_config, "_project_root", lambda: tmp_path)
        monkeypatch.delenv("KELLAI_ENV_FILE", raising=False)
        llm_config._read_dotenv.cache_clear()

        cfg = llm_config.effective_config()

        assert cfg["provider"] == "custom"
        assert cfg["source"] == "VITE_LLM_API_KEY"
        assert cfg["base_url"] == "https://desktop-prod.example.test/v1"
        assert cfg["model"] == "desktop-prod-model"

    async def test_llm_config_reads_common_qwen_bailian_aliases(self, tmp_db, tmp_path, monkeypatch):
        from app.services import llm_config

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "BAILIAN_API_KEY=test-bailian-key",
                    "BAILIAN_BASE_URL=https://bailian.example.test/compatible-mode/v1",
                    "BAILIAN_MODEL=qwen-test-model",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("KELLAI_ENV_FILE", str(env_file))
        llm_config._read_dotenv.cache_clear()

        cfg = llm_config.effective_config()
        diag = llm_config.diagnostics()

        assert cfg["provider"] == "qwen"
        assert cfg["source"] == "BAILIAN_API_KEY"
        assert cfg["base_url"] == "https://bailian.example.test/compatible-mode/v1"
        assert cfg["model"] == "qwen-test-model"
        assert "BAILIAN_API_KEY" in diag["dotenvs"][0]["llm_keys_present"]

    async def test_llm_config_reads_volcengine_ark_vite_aliases(self, tmp_db, tmp_path, monkeypatch):
        from app.services import llm_config

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        desktop_dir = tmp_path / "desktop"
        desktop_dir.mkdir()
        (desktop_dir / ".env.local").write_text(
            "\n".join(
                [
                    "VITE_VOLCENGINE_ARK_API_KEY=test-ark-key",
                    "VITE_VOLCENGINE_ARK_API_BASE=https://ark.example.test/api/v3",
                    "VITE_VOLCENGINE_ARK_MODEL=doubao-test-model",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(llm_config, "_project_root", lambda: tmp_path)
        monkeypatch.delenv("KELLAI_ENV_FILE", raising=False)
        llm_config._read_dotenv.cache_clear()

        cfg = llm_config.effective_config()
        diag = llm_config.diagnostics()

        assert cfg["provider"] == "ark"
        assert cfg["source"] == "VITE_VOLCENGINE_ARK_API_KEY"
        assert cfg["base_url"] == "https://ark.example.test/api/v3"
        assert cfg["model"] == "doubao-test-model"
        assert diag["env_presence"]["VOLCENGINE_ARK_API_KEY"] is True
        assert any("VITE_VOLCENGINE_ARK_API_KEY" in item["llm_keys_present"] for item in diag["dotenvs"])

    async def test_llm_config_reads_zhipu_glm_aliases(self, tmp_db, tmp_path, monkeypatch):
        from app.services import llm_config

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "GLM_API_KEY=test-glm-key",
                    "GLM_API_BASE=https://glm.example.test/api/paas/v4",
                    "GLM_MODEL=glm-test-model",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("KELLAI_ENV_FILE", str(env_file))
        llm_config._read_dotenv.cache_clear()

        cfg = llm_config.effective_config()
        diag = llm_config.diagnostics()

        assert cfg["provider"] == "zhipu"
        assert cfg["source"] == "GLM_API_KEY"
        assert cfg["base_url"] == "https://glm.example.test/api/paas/v4"
        assert cfg["model"] == "glm-test-model"
        assert diag["env_presence"]["GLM_API_KEY"] is True
        assert "GLM_API_KEY" in diag["dotenvs"][0]["llm_keys_present"]

    async def test_llm_config_reads_xiaomi_mimo_token_plan_aliases(self, tmp_db, tmp_path, monkeypatch):
        from app.services import llm_config

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "MIMO_API_KEY=test-mimo-token-plan-key",
                    "MIMO_TOKEN_PLAN_API_BASE=https://token-plan-cn.xiaomimimo.com/v1",
                    "MIMO_MODEL=mimo-v2.5-pro",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("KELLAI_ENV_FILE", str(env_file))
        llm_config._read_dotenv.cache_clear()

        cfg = llm_config.effective_config()
        diag = llm_config.diagnostics()

        assert cfg["provider"] == "mimo"
        assert cfg["source"] == "MIMO_API_KEY"
        assert cfg["base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"
        assert cfg["model"] == "mimo-v2.5-pro"
        assert diag["env_presence"]["MIMO_API_KEY"] is True
        assert "MIMO_API_KEY" in diag["dotenvs"][0]["llm_keys_present"]

    async def test_llm_config_normalizes_saved_provider_aliases(self, tmp_db, monkeypatch):
        from app.services import llm_config

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        public = llm_config.save_config(
            {
                "provider": "doubao",
                "api_key": "saved-ark-key",
                "base_url": "https://ark.saved.test/api/v3",
                "model": "doubao-saved-model",
            }
        )
        effective = llm_config.effective_config()

        assert public["provider"] == "ark"
        assert public["model"] == "doubao-saved-model"
        assert public["base_url"] == "https://ark.saved.test/api/v3"
        assert effective["provider"] == "ark"
        assert effective["model"] == "doubao-saved-model"
        assert effective["base_url"] == "https://ark.saved.test/api/v3"

    async def test_llm_config_normalizes_xiaomi_mimo_provider_alias(self, tmp_db, monkeypatch):
        from app.services import llm_config

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        public = llm_config.save_config(
            {
                "provider": "小米",
                "api_key": "saved-mimo-key",
                "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                "model": "mimo-v2.5-pro",
            }
        )
        effective = llm_config.effective_config()

        assert public["provider"] == "mimo"
        assert public["model"] == "mimo-v2.5-pro"
        assert public["base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"
        assert effective["provider"] == "mimo"
        assert effective["model"] == "mimo-v2.5-pro"
        assert effective["base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"

    async def test_llm_config_save_preserves_custom_model_and_base_url(self, tmp_db, monkeypatch):
        from app.services import llm_config

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        public = llm_config.save_config(
            {
                "provider": "custom",
                "api_key": "saved-compatible-key",
                "base_url": "https://gateway.example.test/v1",
                "model": "saved-model",
            }
        )
        effective = llm_config.effective_config()

        assert public["provider"] == "custom"
        assert public["model"] == "saved-model"
        assert public["base_url"] == "https://gateway.example.test/v1"
        assert effective["provider"] == "custom"
        assert effective["model"] == "saved-model"
        assert effective["base_url"] == "https://gateway.example.test/v1"

    async def test_knowledge_base_search_and_suggest_answer(self, tmp_db):
        from app.services import knowledge_base

        article = knowledge_base.upsert_article(
            {
                "title": "企微接入与优惠政策",
                "content": "企业微信接入需要客服链接或 open_kfid。首月优惠需在客户确认合同后申请，付款后安排交付和培训。",
                "tags": ["企业微信", "优惠", "交付"],
                "source": "test",
            }
        )

        hits = knowledge_base.search_articles("企微怎么接入，能不能优惠", limit=3)
        suggestion = knowledge_base.suggest_answer("客户问企业微信接入和首月优惠怎么回复", customer_context={"stage_label": "已签"}, limit=3)

        assert hits
        assert hits[0]["id"] == article["id"]
        assert suggestion["matched"] is True
        assert "企微接入" in suggestion["answer"] or "企业微信接入" in suggestion["answer"]
        assert suggestion["sources"][0]["id"] == article["id"]

    async def test_quality_inspection_flags_compliance_and_supervisor_review(self, tmp_db):
        from app.channels.base import UnifiedMessage
        from app.services.message_store import save_message
        from app.services.quality_inspection import inspect_customer_conversation

        customer_id = 0
        turns = [
            ("inbound", "价格太贵了，你们能不能优惠？"),
            ("outbound", "绝对保证百分百当天上线，先别担心退款问题。"),
            ("inbound", "你这样乱承诺我不满意，再处理不好我就投诉差评退款，要求主管联系。"),
        ]
        for idx, (direction, content) in enumerate(turns):
            saved = save_message(
                UnifiedMessage(
                    id=f"quality-test-{idx}",
                    customer_id=customer_id,
                    channel_type="wework",
                    contact_id="quality_contact",
                    contact_name="质检客户",
                    direction=direction,
                    content=content,
                    content_type="text",
                    metadata={"source": "test"},
                    created_at=f"2026-06-13T00:0{idx}:00Z",
                )
            )
            customer_id = int(saved.customer_id)

        report = inspect_customer_conversation(customer_id)
        rule_keys = {item["key"] for item in report["failed_rules"]}

        assert report["review_required"] is True
        assert report["score"] < 80
        assert {"compliance_promise", "negative_sentiment", "refund_risk", "handoff_required"}.issubset(rule_keys)
        assert report["manager_report"]["suggested_action"]
        assert report["recommendations"]

    async def test_service_ticket_handoff_resolves_and_rehosts_ai(self, tmp_db):
        from app.channels.base import UnifiedMessage
        from app.services.message_store import save_message
        from app.services.service_tickets import (
            assign_service_ticket,
            create_ticket_from_quality,
            resolve_service_ticket,
            service_ticket_summary,
        )

        customer_id = 0
        turns = [
            ("inbound", "你们价格太贵，先问问。"),
            ("outbound", "绝对保证百分百当天上线。"),
            ("inbound", "我不满意，要求主管联系，不然投诉退款。"),
        ]
        for idx, (direction, content) in enumerate(turns):
            saved = save_message(
                UnifiedMessage(
                    id=f"ticket-test-{idx}",
                    customer_id=customer_id,
                    channel_type="wework",
                    contact_id="ticket_contact",
                    contact_name="工单客户",
                    direction=direction,
                    content=content,
                    content_type="text",
                    metadata={"source": "test"},
                    created_at=f"2026-06-13T01:0{idx}:00Z",
                )
            )
            customer_id = int(saved.customer_id)

        ticket = create_ticket_from_quality(customer_id, assignee="主管A", sla_minutes=20)
        assigned = assign_service_ticket(ticket["id"], "主管A", actor="pytest")
        resolved = resolve_service_ticket(ticket["id"], "已安抚客户并改用合规话术。", actor="pytest")
        summary = service_ticket_summary(customer_id)
        event_actions = {item["action"] for item in resolved["events"]}

        assert ticket["status"] == "open"
        assert assigned["status"] == "assigned"
        assert resolved["status"] == "resolved"
        assert resolved["ai_rehost_action"]
        assert {"created", "assigned", "resolved", "rehosted_to_ai"}.issubset(event_actions)
        assert summary["resolved"] == 1
        assert summary["latest"]["id"] == ticket["id"]

    async def test_service_learning_persists_quality_ticket_sop(self, tmp_db):
        from app.channels.base import UnifiedMessage
        from app.services.message_store import save_message
        from app.services.service_learning import run_service_learning
        from app.services.service_tickets import assign_service_ticket, create_ticket_from_quality, resolve_service_ticket

        customer_id = 0
        turns = [
            ("inbound", "价格太贵，我要找主管，不然投诉退款。"),
            ("outbound", "绝对保证百分百当天上线。"),
            ("inbound", "这种乱承诺我不满意，要求主管处理。"),
        ]
        for idx, (direction, content) in enumerate(turns):
            saved = save_message(
                UnifiedMessage(
                    id=f"learning-test-{idx}",
                    customer_id=customer_id,
                    channel_type="wework",
                    contact_id="learning_contact",
                    contact_name="自学习客户",
                    direction=direction,
                    content=content,
                    content_type="text",
                    metadata={"source": "test"},
                    created_at=f"2026-06-13T02:0{idx}:00Z",
                )
            )
            customer_id = int(saved.customer_id)

        ticket = create_ticket_from_quality(customer_id, assignee="主管A", sla_minutes=20)
        assign_service_ticket(ticket["id"], "主管A", actor="pytest")
        resolve_service_ticket(ticket["id"], "已安抚客户并改用合规话术。", actor="pytest")

        learning = run_service_learning(customer_id, persist=True)

        assert learning["passed"] is True
        assert learning["article"]["id"] == f"service_learning_{customer_id}"
        assert learning["metrics"]["ticket_resolved"] == 1
        assert learning["metrics"]["ai_rehosted"] == 1
        assert learning["metrics"]["high_risk_cases"] >= 1
        assert learning["recommendations"]
        assert any(hit["id"] == learning["article"]["id"] for hit in learning["search_hits"])

    async def test_service_learning_search_is_stable_for_repeated_audit_titles(self, tmp_db):
        from app.channels.base import UnifiedMessage
        from app.services.message_store import save_message
        from app.services.service_learning import run_service_learning
        from app.services.service_tickets import assign_service_ticket, create_ticket_from_quality, resolve_service_ticket

        customer_ids: list[int] = []
        for suffix in ("a", "b"):
            customer_id = 0
            for idx, (direction, content) in enumerate(
                [
                    ("inbound", "价格太贵，我要找主管，不然投诉退款。"),
                    ("outbound", "绝对保证百分百当天上线。"),
                    ("inbound", "这种乱承诺我不满意，要求主管处理。"),
                ]
            ):
                saved = save_message(
                    UnifiedMessage(
                        id=f"learning-repeat-{suffix}-{idx}",
                        customer_id=customer_id,
                        channel_type="wework",
                        contact_id=f"learning_repeat_{suffix}",
                        contact_name="闭环验收-抖音客户",
                        direction=direction,
                        content=content,
                        content_type="text",
                        metadata={"source": "test"},
                        created_at=f"2026-06-13T03:0{idx}:00Z",
                    )
                )
                customer_id = int(saved.customer_id)
            ticket = create_ticket_from_quality(customer_id, assignee="主管A", sla_minutes=20)
            assign_service_ticket(ticket["id"], "主管A", actor="pytest")
            resolve_service_ticket(ticket["id"], "已安抚客户并改用合规话术。", actor="pytest")
            customer_ids.append(customer_id)
            learning = run_service_learning(customer_id, persist=True)
            assert learning["passed"] is True

        latest = run_service_learning(customer_ids[-1], persist=True)
        assert latest["article"]["id"] == f"service_learning_{customer_ids[-1]}"
        assert latest["search_hits"][0]["id"] == latest["article"]["id"]

    async def test_outbound_call_executes_phone_followup_and_pipeline(self, tmp_db):
        from app.channels.base import UnifiedMessage
        from app.services.growth_loop import customer_message_context
        from app.services.message_store import get_messages, save_message
        from app.services.outbound_call import execute_outbound_call, outbound_call_summary, plan_outbound_call

        saved = save_message(
            UnifiedMessage(
                id="outbound-call-seed-1",
                customer_id=0,
                channel_type="douyin",
                contact_id="outbound_call_contact",
                contact_name="外呼客户",
                direction="inbound",
                content="我想看方案和报价，有时间可以演示一下吗？",
                content_type="text",
                metadata={"source": "test"},
                created_at="2026-06-13T04:00:00Z",
            )
        )
        customer_id = int(saved.customer_id)

        planned = plan_outbound_call(customer_id, purpose="quote_follow_up", actor="pytest")
        executed = execute_outbound_call(planned["id"], outcome="demo_booked", actor="pytest")
        summary = outbound_call_summary(customer_id)
        ctx = customer_message_context(customer_id)
        phone_messages = get_messages(customer_id, channel_type="phone", limit=10)

        assert planned["status"] == "planned"
        assert planned["script"]["opening"]
        assert executed["status"] == "completed"
        assert executed["outcome"] == "demo_booked"
        assert len(executed["transcript"]) >= 3
        assert len(executed["message_ids"]) >= 2
        assert summary["completed"] == 1
        assert summary["phone_message_count"] >= 2
        assert ctx["stage"] == "quoted"
        assert "phone" in ctx["channel_sources"]
        assert ctx["next_action"]
        assert len([m for m in phone_messages if m.metadata.get("source") == "outbound_call"]) >= 2

    async def test_self_service_resolution_answers_and_handoffs(self, tmp_db):
        from app.channels.base import UnifiedMessage
        from app.services.knowledge_base import upsert_article
        from app.services.message_store import get_messages, save_message
        from app.services.self_service_resolution import run_self_service_resolution, self_service_summary
        from app.services.service_tickets import service_ticket_summary

        saved = save_message(
            UnifiedMessage(
                id="self-service-seed-1",
                customer_id=0,
                channel_type="wework",
                contact_id="self_service_contact",
                contact_name="自助客户",
                direction="inbound",
                content="企微接入和付款后交付怎么安排？",
                content_type="text",
                metadata={"source": "test"},
                created_at="2026-06-13T05:00:00Z",
            )
        )
        customer_id = int(saved.customer_id)
        article = upsert_article(
            {
                "id": "self_service_test_article",
                "title": "企微接入与付款后交付",
                "content": "企微接入需要提供客服链接或 open_kfid。付款后发送交付清单，并安排渠道配置和团队培训。",
                "tags": ["企微", "交付", "付款"],
                "source": "pytest",
            }
        )

        resolved = run_self_service_resolution(
            customer_id,
            query="企微接入和付款后交付怎么安排？",
            channel_type="wework",
            actor="pytest",
        )
        handoff = run_self_service_resolution(
            customer_id,
            query="火星门店硬件维修 SLA 与离线探针校准流程是什么？",
            channel_type="wework",
            actor="pytest",
        )
        summary = self_service_summary(customer_id)
        tickets = service_ticket_summary(customer_id)
        messages = get_messages(customer_id, limit=20)

        assert article["id"] == "self_service_test_article"
        assert resolved["status"] == "resolved"
        assert resolved["matched"] is True
        assert any(src["id"] == article["id"] for src in resolved["sources"])
        assert len(resolved["message_ids"]) >= 2
        assert handoff["status"] == "handoff_required"
        assert handoff["ticket_id"]
        assert summary["resolved"] == 1
        assert summary["handoff"] == 1
        assert tickets["open"] >= 1
        assert len([m for m in messages if m.metadata.get("source") == "self_service_resolution"]) >= 3

    async def test_agent_assist_autofills_intake_and_recommends_actions(self, tmp_db):
        from app.channels.base import UnifiedMessage
        from app.services.agent_assist import build_agent_assist
        from app.services.knowledge_base import upsert_article
        from app.services.message_store import save_message
        from app.services.pipeline import load_pipeline

        upsert_article(
            {
                "id": "agent_assist_test_article",
                "title": "企微和小程序统一接待方案",
                "content": "客户需要抖音、企微和小程序统一接待时，先确认门店数、消息量、预算和上线时间，再生成报价。",
                "tags": ["坐席助手", "自动填单", "企微"],
                "source": "pytest",
            }
        )
        saved = save_message(
            UnifiedMessage(
                id="agent-assist-seed-1",
                customer_id=0,
                channel_type="douyin",
                contact_id="agent_assist_contact",
                contact_name="自动填单客户",
                direction="inbound",
                content="我们是三家门店，想把抖音、企微和小程序统一接待。电话 13800138000，预算合适这周签。",
                content_type="text",
                metadata={"source": "test"},
                created_at="2026-06-13T06:00:00Z",
            )
        )
        customer_id = int(saved.customer_id)

        draft = build_agent_assist(customer_id, persist=False, actor="pytest")
        applied = build_agent_assist(customer_id, persist=True, actor="pytest")
        pipeline = load_pipeline(customer_id)

        assert draft["status"] == "draft"
        assert draft["passed"] is True
        assert applied["status"] == "applied"
        assert applied["persisted"] is True
        assert applied["draft"]["contact_phone"] == "13800138000"
        assert applied["draft"]["need_mobile"] is True
        assert applied["knowledge_recommendations"]
        assert applied["next_actions"]
        assert pipeline["intake_form"]["requirement_desc"]
        assert pipeline["intake_form"]["autofill_source"] == "agent_assist"
        assert pipeline["agent_assist"]["status"] == "applied"
        assert pipeline["stage"] == "intake_done"

    async def test_closed_loop_audit_keeps_core_checks_but_fails_without_required_llm(self, tmp_db, monkeypatch):
        from app.services.closed_loop_audit import latest_closed_loop_audit_report, run_closed_loop_audit

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        out = await run_closed_loop_audit(require_llm=True, target_stage="signed")

        checks = {item["key"]: item for item in out["checks"]}
        assert out["passed"] is False
        assert checks["llm_ready"]["passed"] is False
        assert checks["llm_full_flow"]["passed"] is False
        assert checks["customer_created"]["passed"] is True
        assert checks["messages_persisted"]["passed"] is True
        assert checks["pipeline_auto_progressed"]["passed"] is True
        assert checks["ai_intent"]["passed"] is True
        assert checks["memory_continuity_loop"]["passed"] is True
        assert checks["agent_service_ops_loop"]["passed"] is True
        assert checks["quality_inspection_loop"]["passed"] is True
        assert checks["human_handoff_ticket_loop"]["passed"] is True
        assert checks["service_learning_loop"]["passed"] is True
        assert checks["outbound_call_loop"]["passed"] is True
        assert checks["self_service_resolution_loop"]["passed"] is True
        assert checks["agent_assist_autofill_loop"]["passed"] is True
        assert checks["multimodal_service_loop"]["passed"] is True
        assert checks["redbear_benchmark_coverage"]["passed"] is False
        assert "price_objection" in checks["agent_service_ops_loop"]["details"]["risk_keys"]
        assert "omnichannel_one_id" in checks["agent_service_ops_loop"]["details"]["management_keys"]
        assert "compliance_promise" in checks["quality_inspection_loop"]["details"]["rule_keys"]
        assert "rehosted_to_ai" in checks["human_handoff_ticket_loop"]["details"]["event_actions"]
        assert checks["service_learning_loop"]["details"]["metrics"]["ai_rehosted"] >= 1
        assert checks["outbound_call_loop"]["details"]["phone_message_count"] >= 2
        assert checks["self_service_resolution_loop"]["details"]["summary"]["handoff"] >= 1
        assert checks["agent_assist_autofill_loop"]["details"]["knowledge_count"] >= 1
        assert "image" in checks["multimodal_service_loop"]["details"]["content_types"]
        assert "audio" in checks["multimodal_service_loop"]["details"]["content_types"]
        assert checks["sales_revenue_loop"]["passed"] is True
        assert checks["customer_management_loop"]["passed"] is True
        assert checks["llm_settings_loop"]["passed"] is True
        assert checks["knowledge_base_loop"]["passed"] is True
        assert checks["content_growth_loop"]["passed"] is True
        assert checks["scout_lead_loop"]["passed"] is True
        assert checks["flow_automation_loop"]["passed"] is True
        assert checks["finance_decision_loop"]["passed"] is True
        assert checks["open_platform_loop"]["passed"] is True
        assert checks["channel_onboarding_loop"]["passed"] is True
        assert out["benchmark_profile"]["summary"]["failed_required"] == 1
        assert out["benchmark_profile"]["failed_required_labels"] == ["真实大模型 Agent 成交链路"]
        assert out["audit_customer_id"] > 0
        latest = latest_closed_loop_audit_report()
        assert latest is not None
        assert latest["audit_id"] == out["audit_id"]
        assert latest["passed"] is False
        assert latest["failure_reason"] == out["failure_reason"]

    async def test_closed_loop_audit_requires_llm_probe_success_even_when_key_exists(self, tmp_db, monkeypatch):
        from app.services import closed_loop_audit

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)
        def fake_public_config():
            return {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "ready": True,
                "connected": False,
                "verified": False,
                "message": "已保存 Key，尚未通过连通验证",
            }

        def fake_probe_llm_connection(*, update_disk: bool = True, timeout_sec: float = 10.0):
            return {
                "success": False,
                "connected": False,
                "checked_at": "2026-06-13T00:00:00+00:00",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "latency_ms": 12,
                "error": "HTTP 401: invalid api key",
            }

        async def fake_llm_full_flow(**kwargs):
            return {
                "mode": "llm_generation_failed",
                "llm_ready": True,
                "llm_customer_turns": 0,
                "llm_agent_turns": 0,
                "customer_id": 0,
                "final_stage": "idle",
                "passed": False,
                "failure_reason": "LLM 探测失败，不能执行真实客户行为闭环",
            }

        monkeypatch.setattr(closed_loop_audit, "public_config", fake_public_config)
        monkeypatch.setattr(closed_loop_audit, "probe_llm_connection", fake_probe_llm_connection)
        monkeypatch.setattr(closed_loop_audit, "run_llm_full_flow_simulation", fake_llm_full_flow)

        out = await closed_loop_audit.run_closed_loop_audit(require_llm=True, target_stage="signed")

        checks = {item["key"]: item for item in out["checks"]}
        assert out["passed"] is False
        assert checks["llm_ready"]["label"] == "真实 LLM 已连通"
        assert checks["llm_ready"]["passed"] is False
        assert checks["llm_ready"]["details"]["probe_success"] is False
        assert "invalid api key" in checks["llm_ready"]["details"]["probe_error"]
        assert checks["llm_full_flow"]["passed"] is False
        assert out["failure_reason"] == "真实 LLM 已连通；LLM 客户行为到签约闭环；红熊/黑熊 AI 对标能力覆盖"
        assert checks["redbear_benchmark_coverage"]["passed"] is False
        assert out["benchmark_profile"]["failed_required_labels"] == ["真实大模型 Agent 成交链路"]

    async def test_closed_loop_audit_dev_mode_passes_without_required_llm(self, tmp_db, monkeypatch):
        from app.services.closed_loop_audit import run_closed_loop_audit

        for key in LLM_ENV_CANDIDATES:
            monkeypatch.delenv(key, raising=False)

        out = await run_closed_loop_audit(require_llm=False, target_stage="signed")

        checks = {item["key"]: item for item in out["checks"]}
        assert out["passed"] is True
        assert checks["llm_ready"]["required"] is False
        assert checks["llm_full_flow"]["required"] is False
        assert checks["llm_full_flow"]["details"]["mode"] == "scripted_fallback"
        assert checks["manual_stage_update"]["passed"] is True
        for key in (
            "sales_revenue_loop",
            "customer_management_loop",
            "llm_settings_loop",
            "knowledge_base_loop",
            "memory_continuity_loop",
            "agent_service_ops_loop",
            "quality_inspection_loop",
            "human_handoff_ticket_loop",
            "service_learning_loop",
            "outbound_call_loop",
            "self_service_resolution_loop",
            "content_growth_loop",
            "scout_lead_loop",
            "flow_automation_loop",
            "finance_decision_loop",
            "open_platform_loop",
            "channel_onboarding_loop",
        ):
            assert checks[key]["passed"] is True


# ---------------------------------------------------------------------------
# HTTP 客户端基础
# ---------------------------------------------------------------------------


class TestHTTPClient:
    async def test_cached_token_refreshes_once(self):
        from app.channels.http_client import CachedToken

        calls = []

        async def refresh():
            calls.append(1)
            return ("T-1", 60)

        tok = CachedToken(refresh, ttl_sec=60)
        v1 = await tok.get()
        v2 = await tok.get()
        assert v1 == "T-1"
        assert v2 == "T-1"
        assert len(calls) == 1

    async def test_token_bucket_consume(self):
        from app.channels.http_client import TokenBucket

        b = TokenBucket(capacity=3, refill_per_sec=10)
        # 前 3 个立即返回
        t0 = await b.acquire()
        t1 = await b.acquire()
        t2 = await b.acquire()
        assert t0 == 0.0
        assert t1 == 0.0
        assert t2 == 0.0
