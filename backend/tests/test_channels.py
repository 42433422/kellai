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


# ---------------------------------------------------------------------------
# 夹具：每个测试独立的临时 SQLite
# ---------------------------------------------------------------------------


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

    async def test_bot_webhook_configured_test_ok(self, monkeypatch):
        from app.channels.wecom import WeComAdapter

        monkeypatch.setenv("KELLAI_WECOM_BOT_WEBHOOK", "https://example.com/bot/abc")
        a = WeComAdapter()
        out = await a.test_connection()
        assert out["connected"] is True
        assert "Webhook" in out["message"]

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
# WeChatAdapter（委托企微）
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


# ---------------------------------------------------------------------------
# DouyinAdapter
# ---------------------------------------------------------------------------


class TestDouyinAdapter:
    async def test_unconfigured(self):
        from app.channels.douyin import DouyinAdapter

        a = DouyinAdapter()
        out = await a.send_message("open_x", "hello")
        assert out["success"] is False
        assert "未配置" in out["error"]
        out = await a.test_connection()
        assert out["connected"] is False

    async def test_token_then_send(self, monkeypatch):
        from app.channels.douyin import DouyinAdapter

        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_KEY", "ck")
        monkeypatch.setenv("KELLAI_DOUYIN_CLIENT_SECRET", "cs")
        a = DouyinAdapter()

        # token 由 CachedToken 内部调用 _fetch_token 拿（不发 HTTP），send 走 client.post
        async def fake_token():
            return ("DT-1", 7200)

        send_resp = MagicMock(status_code=200)
        send_resp.json.return_value = {
            "errcode": 0,
            "errmsg": "ok",
            "data": {"message_id": "DM-1"},
        }
        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=send_resp)

        with patch.object(a, "_fetch_token", fake_token), \
             patch.object(a, "_get_client", AsyncMock(return_value=fake_client)):
            out = await a.send_message("open_x", "hi")
        assert out["success"] is True
        assert out["message_id"] == "DM-1"
        assert fake_client.post.await_count == 1
        send_call = fake_client.post.await_args
        assert "im/message/send" in send_call.args[0]


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


# ---------------------------------------------------------------------------
# 收件箱：适配器 receive_messages 必须能消费 push_inbox 写入
# ---------------------------------------------------------------------------


class TestInboxEndToEnd:
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
