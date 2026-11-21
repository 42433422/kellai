from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("KELLAI_APP_ENV", "development")
os.environ.setdefault("KELLAI_JWT_SECRET", "test-secret-for-pytest-only")
os.environ.setdefault("KELLAI_PASSWORD_SALT", "test-salt-for-pytest-only")
os.environ.setdefault("KELLAI_DOUYIN_TOKEN_KEY", "test-douyin-token-key")

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def portal(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    from app.services import crm_store, douyin_channel, douyin_web_portal

    importlib.reload(crm_store)
    importlib.reload(douyin_channel)
    return importlib.reload(douyin_web_portal)


def test_extract_token_accepts_fullscreen_url_and_raw_token(portal):
    assert (
        portal.extract_token("https://dyylk.yidongwl.com/?token=abc123456%2Bxyz")
        == "abc123456+xyz"
    )
    assert portal.extract_token("raw-token-value") == "raw-token-value"
    assert portal.extract_token("https://dyylk.yidongwl.com/") == ""


def test_extract_token_accepts_common_paste_formats(portal):
    assert portal.extract_token(" token=abc123456%2Bxyz ") == "abc123456+xyz"
    assert portal.extract_token("'Bearer abc123456'") == "abc123456"
    assert portal.extract_token("token: abc123456") == "abc123456"
    assert (
        portal.extract_token(
            "https://dyylk.yidongwl.com/IntelligentInteraction/chat"
            "#/chat?token=fragment123"
        )
        == "fragment123"
    )
    assert (
        portal.extract_token(
            "https%3A%2F%2Fdyylk.yidongwl.com%2F%3Ftoken%3Dencoded123"
        )
        == "encoded123"
    )


def test_post_maps_http_401_to_token_expired_message(portal, monkeypatch):
    class FakeResponse:
        status_code = 401

        @staticmethod
        def json():
            return {"code": 401, "msg": "unauthorized"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(portal.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    with pytest.raises(
        portal.DouyinWebPortalAuthError,
        match="网站 Token 无效或已过期",
    ):
        portal.asyncio.run(portal._post("not-a-real-token", "service/service/index"))


def test_portal_token_encryption_does_not_require_client_secret(portal, monkeypatch):
    monkeypatch.delenv("KELLAI_DOUYIN_WEB_PORTAL_STORAGE_KEY", raising=False)
    monkeypatch.delenv("KELLAI_DOUYIN_STORAGE_KEY", raising=False)
    monkeypatch.delenv("KELLAI_DOUYIN_CLIENT_SECRET", raising=False)

    encrypted = portal._encrypt_token("website-session-token")

    assert encrypted != "website-session-token"
    assert portal._decrypt_token(encrypted) == "website-session-token"
    assert portal._token_key_path().exists()


def test_resume_connected_monitors_starts_saved_connection(portal, monkeypatch):
    portal.ensure_schema()
    with portal._conn() as conn:
        conn.execute(
            """
            INSERT INTO kellai_douyin_web_portal
                (team_id, token_enc, status, updated_at)
            VALUES (32, 'encrypted-token', 'connected', ?)
            """,
            (portal._now_iso(),),
        )

    started: list[int] = []

    async def fake_start_monitor(team_id: int):
        started.append(team_id)
        return {"monitor_running": True}

    monkeypatch.setattr(portal, "start_monitor", fake_start_monitor)

    result = portal.asyncio.run(portal.resume_connected_monitors())

    assert result == {"started": 1, "failed": 0}
    assert started == [32]


def test_message_content_normalizes_non_text_messages(portal):
    assert portal._message_content("text", "你好") == "你好"
    assert portal._message_content("image", "") == "[图片]"
    assert portal._message_content("retain_consult_card", "") == "[客户提交了留资卡]"


def test_stable_message_id_prefers_remote_id(portal):
    value = portal._stable_message_id(
        1,
        "customer-1",
        {"server_message_id": "server-123", "content": "hello"},
    )
    assert value == "douyin:web:server-123"


def test_reused_remote_message_id_keeps_distinct_messages(portal):
    account = {"id": 8, "name": "抖音账号 A"}
    session = {
        "from_open_id": "customer-open-id",
        "conversation_short_id": "conversation-1",
        "nick_name": "真实客户",
    }
    inbound = {
        "server_message_id": "reused-id",
        "from_open_id": "customer-open-id",
        "content": "客户消息",
        "message_type": "text",
        "createtime": 1_700_000_000,
    }
    outbound = {
        "server_message_id": "reused-id",
        "from_open_id": "service-open-id",
        "content": "客服回复",
        "message_type": "text",
        "createtime": 1_700_000_010,
    }

    assert portal._ingest_message(
        team_id=3,
        account=account,
        session=session,
        item=inbound,
    )
    assert portal._ingest_message(
        team_id=3,
        account=account,
        session=session,
        item=outbound,
    )

    import sqlite3

    from app.services.crm_store import _crm_db_path

    with sqlite3.connect(str(_crm_db_path())) as conn:
        rows = conn.execute(
            """
            SELECT content, direction
            FROM kellai_messages
            ORDER BY created_at
            """
        ).fetchall()
    assert rows == [("客户消息", "inbound"), ("客服回复", "outbound")]


def test_websocket_private_message_is_saved_to_unified_store(portal):
    payload = {
        "type": "webhooks",
        "data": {
            "msg_type": "private_msg",
            "memberInfo": {"id": 8, "name": "抖音账号 A"},
            "userInfo": {
                "id": 9,
                "member_id": 8,
                "from_open_id": "customer-open-id",
                "conversation_short_id": "conversation-1",
                "nick_name": "真实客户",
                "avatar": "https://example.com/a.png",
                "content": "咨询价格",
                "message_type": "text",
                "createtime": 1_700_000_000,
                "not_read_msg_num": 1,
            },
            "msgData": {
                "server_message_id": "message-1",
                "from_open_id": "customer-open-id",
                "content": "咨询价格",
                "message_type": "text",
                "createtime": 1_700_000_000,
            },
        },
    }

    assert portal.asyncio.run(portal._handle_websocket_payload(3, payload)) is True
    assert portal.asyncio.run(portal._handle_websocket_payload(3, payload)) is False

    import json
    import sqlite3

    from app.services.crm_store import _crm_db_path

    with sqlite3.connect(str(_crm_db_path())) as conn:
        row = conn.execute(
            """
            SELECT content, direction, metadata_json
            FROM kellai_messages
            WHERE id = 'douyin:web:message-1'
            """
        ).fetchone()
    assert row is not None
    assert row[0] == "咨询价格"
    assert row[1] == "inbound"
    assert json.loads(row[2])["source"] == "douyin_web_portal"


def test_synced_outbound_replaces_desktop_provisional(portal):
    from app.channels.base import UnifiedMessage
    from app.services.message_store import save_message

    save_message(
        UnifiedMessage(
            id="provisional-1",
            customer_id=88,
            channel_type="douyin",
            contact_id="customer-open-id",
            contact_name="真实客户",
            direction="outbound",
            content="桌面自动回复",
            content_type="text",
                metadata={
                    "source": "douyin_desktop_automation",
                    "pending_portal_sync": True,
                    "team_id": 3,
                },
            created_at="2023-11-14T22:13:20+00:00",
        )
    )
    assert portal._ingest_message(
        team_id=3,
        account={"id": 8, "name": "抖音账号 A"},
        session={
            "from_open_id": "customer-open-id",
            "conversation_short_id": "conversation-1",
            "nick_name": "真实客户",
        },
        item={
            "server_message_id": "remote-outbound-1",
            "from_open_id": "service-open-id",
            "content": "桌面自动回复",
            "message_type": "text",
            "createtime": 1_700_000_000,
        },
    )

    import sqlite3

    from app.services.crm_store import _crm_db_path

    with sqlite3.connect(str(_crm_db_path())) as conn:
        rows = conn.execute(
            """
            SELECT id, customer_id, metadata_json
            FROM kellai_messages
            WHERE contact_id = 'customer-open-id'
            """
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "douyin:web:remote-outbound-1"
    assert rows[0][1] == 88
    assert json.loads(rows[0][2])["source"] == "douyin_web_portal"


def _portal_live_input(message_id="live-message"):
    from datetime import datetime, timezone
    return {
        "team_id": 3,
        "account": {"id": 8, "name": "抖音账号 A"},
        "session": {"from_open_id": "live-contact", "conversation_short_id": "live-conversation", "nick_name": "真实客户"},
        "item": {"server_message_id": message_id, "from_open_id": "live-contact", "content": "实时咨询",
                 "message_type": "text", "createtime": int(datetime.now(timezone.utc).timestamp())},
    }


def _enable_portal_auto_reply(monkeypatch):
    from app.services import auto_reply_runtime
    monkeypatch.setattr(auto_reply_runtime, "_enabled_config", lambda: {
        "autoReplyEnabled": True, "autoReplyStages": [], "confirmScenarios": []})


@pytest.mark.parametrize("recovery", ["duplicate", "history_duplicate", "periodic_replay", "common_consumer"])
def test_queue_failure_is_replayed_without_replacing_saved_message(portal, monkeypatch, recovery):
    import sqlite3
    from app.services import auto_reply_runtime, channel_ingest, douyin_channel
    from app.channels import douyin

    _enable_portal_auto_reply(monkeypatch)
    original_enqueue = auto_reply_runtime.enqueue_message
    monkeypatch.setattr(auto_reply_runtime, "enqueue_message", lambda _: (_ for _ in ()).throw(RuntimeError("queue unavailable")))
    payload = _portal_live_input()
    with pytest.raises(RuntimeError, match="queue unavailable"):
        portal._ingest_message(**payload)
    with sqlite3.connect(str(portal._crm_db_path())) as conn:
        assert conn.execute("SELECT consumed FROM kellai_channel_inbox WHERE team_id=3").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM kellai_messages WHERE team_id=3").fetchone()[0] == 1
        conn.execute("UPDATE kellai_messages SET is_read=1 WHERE team_id=3")
    monkeypatch.setattr(auto_reply_runtime, "enqueue_message", original_enqueue)
    if recovery in {"duplicate", "history_duplicate"}:
        assert portal._ingest_message(**payload, historical=recovery == "history_duplicate")
    elif recovery == "periodic_replay":
        assert portal._replay_pending_portal_inbox(3) == (1, 0)
    else:
        monkeypatch.setattr(douyin_channel, "remote_bridge_enabled", lambda: False)
        monkeypatch.setattr(douyin, "remote_bridge_enabled", lambda: False)
        result = portal.asyncio.run(channel_ingest.sync_inbox(team_id=3, channel_type="douyin"))
        assert result["success"] and result["data"]["auto_reply_queued"] == 1
    with sqlite3.connect(str(portal._crm_db_path())) as conn:
        assert conn.execute("SELECT consumed FROM kellai_channel_inbox WHERE team_id=3").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*), MIN(is_read) FROM kellai_messages WHERE team_id=3").fetchone() == (1, 1)
        assert conn.execute("SELECT COUNT(*) FROM kellai_auto_reply_jobs WHERE team_id=3").fetchone()[0] == 1
    assert not portal._ingest_message(**payload)


def test_save_failure_leaves_durable_original_payload_for_recovery(portal, monkeypatch):
    from app.services import auto_reply_runtime
    _enable_portal_auto_reply(monkeypatch)
    original_save = portal.save_message
    payload = _portal_live_input("failed-before-save")
    monkeypatch.setattr(portal, "save_message", lambda _: (_ for _ in ()).throw(RuntimeError("save unavailable")))
    with pytest.raises(RuntimeError, match="save unavailable"):
        portal._ingest_message(**payload)
    monkeypatch.setattr(portal, "save_message", original_save)
    assert portal._replay_pending_portal_inbox(3) == (1, 0)
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"pending": 1}


def test_recent_poll_history_is_explicitly_historical_but_new_websocket_is_live(portal, monkeypatch):
    import sqlite3
    from app.services import auto_reply_runtime
    _enable_portal_auto_reply(monkeypatch)
    payload = _portal_live_input("history-message")
    monkeypatch.setattr(portal, "_stored_token", lambda _: "test-token")

    async def respond(_token, endpoint, body=None):
        if endpoint.endswith("/index"):
            return [payload["account"]]
        if endpoint.endswith("/getSessionList"):
            return [payload["session"]]
        if endpoint.endswith("/getMsgLog"):
            assert body["limit"] == 20
            return {"data": [payload["item"]]}
        raise AssertionError(endpoint)

    monkeypatch.setattr(portal, "_post", respond)
    summary = portal.asyncio.run(portal.sync_messages(3))
    assert summary["messages"] == 1 and summary["history_errors"] == 0
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {}
    with sqlite3.connect(str(portal._crm_db_path())) as conn:
        saved = json.loads(conn.execute("SELECT metadata_json FROM kellai_messages WHERE team_id=3").fetchone()[0])
        assert saved["historical"] is True
        assert saved["provider_created_at"] == payload["item"]["createtime"]
    item = {**payload["item"], "server_message_id": "new-websocket-message", "createtime": payload["item"]["createtime"] + 1}
    websocket_payload = {"type": "webhooks", "data": {
        "msg_type": "private_msg", "memberInfo": payload["account"], "userInfo": payload["session"], "msgData": item}}
    assert portal.asyncio.run(portal._handle_websocket_payload(3, websocket_payload))
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"pending": 1}


def test_portal_media_is_not_relabelled_text_for_auto_reply(portal, monkeypatch):
    from app.services import auto_reply_runtime, message_store
    _enable_portal_auto_reply(monkeypatch)
    payload = _portal_live_input("image-message")
    payload["item"].update(message_type="image", content="")
    assert portal._ingest_message(**payload)
    rows = message_store.list_inbox("douyin", team_id=3, include_consumed=True)
    assert rows[0]["content_type"] == "image"
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {}


def test_websocket_without_provider_time_cannot_auto_reply(portal, monkeypatch):
    from app.services import auto_reply_runtime
    _enable_portal_auto_reply(monkeypatch)
    payload = _portal_live_input("missing-provider-time")
    payload["item"].pop("createtime")
    assert portal._ingest_message(**payload)
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {}
