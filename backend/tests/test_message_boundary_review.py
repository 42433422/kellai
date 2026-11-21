"""Regressions found by the independent message boundary review."""

from __future__ import annotations

import sqlite3

import pytest

from app.channels.base import UnifiedMessage
from app.services import auto_reply_runtime, channel_ingest, growth_loop, message_store, workforce_routing
from app.services.tenant_context import tenant_scope


@pytest.mark.asyncio
async def test_inbox_retry_preserves_read_state_and_newer_crm_context(monkeypatch, tmp_path):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(growth_loop, "resolve_customer_for_message", lambda _msg: {"customer_id": 7})
    monkeypatch.setattr(workforce_routing, "auto_assign_customer", lambda **_kw: None)
    applied = []
    monkeypatch.setattr(growth_loop, "apply_message_to_growth_loop", lambda msg: applied.append(msg.id))

    def queue_failure(_msg):
        raise sqlite3.OperationalError("auto queue temporarily unavailable")

    monkeypatch.setattr(auto_reply_runtime, "enqueue_message", queue_failure)
    with tenant_scope(7):
        old_id = message_store.push_inbox("wechat", contact_id="customer-openid", direction="inbound",
                                         content="旧消息", msg_id="older-message")
        first = await channel_ingest.sync_inbox(team_id=7, channel_type="wechat")
        assert first["success"] is False
        assert message_store.mark_as_read([old_id], team_id=7) == 1
        message_store.save_message(UnifiedMessage(
            id="newer-message", customer_id=7, channel_type="wechat", contact_id="customer-openid", contact_name="客户",
            direction="inbound", content="新消息", created_at="2099-01-02T00:00:00+00:00", metadata={"team_id": 7},
        ))
        monkeypatch.setattr(auto_reply_runtime, "enqueue_message", lambda _msg: False)
        restored = await channel_ingest.sync_inbox(team_id=7, channel_type="wechat")
    assert restored["success"] is True
    with sqlite3.connect(str(tmp_path / "kellai.db")) as conn:
        read_flag = conn.execute("SELECT is_read FROM kellai_messages WHERE team_id=7 AND id=?", (old_id,)).fetchone()[0]
    assert read_flag == 1, "replaying an inbox item must not turn a read message unread"
    assert applied == ["older-message", "newer-message"], "replaying old inbox data must not rewind CRM context"


def test_equal_contact_ids_on_different_channels_do_not_merge_customers(monkeypatch, tmp_path):
    from app.services.pipeline import create_customer, save_pipeline
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    with tenant_scope(7):
        old = create_customer({"name": "Telegram customer", "source": "telegram"})
        old["contact_id"] = "123456"
        save_pipeline(old)
        resolved = growth_loop.resolve_customer_for_message(UnifiedMessage(
            id="wechat-first", customer_id=0, direction="inbound", created_at="2026-11-21T00:00:00+00:00",
            channel_type="wechat", contact_id="123456", contact_name="Wechat customer",
            content="first message", metadata={"team_id": 7},
        ))
        assert resolved["customer_id"] != old["customer_id"]
        same_channel = growth_loop.resolve_customer_for_message(UnifiedMessage(
            id="telegram-second", customer_id=0, direction="inbound", created_at="2026-11-21T00:00:01+00:00",
            channel_type="telegram", contact_id="123456", contact_name="Original customer",
            content="new message", metadata={"team_id": 7},
        ))
        assert same_channel["customer_id"] == old["customer_id"]


def test_late_first_arrival_does_not_reopen_or_rewind_current_customer(monkeypatch, tmp_path):
    from app.services.pipeline import create_customer, load_pipeline, save_pipeline
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    with tenant_scope(7):
        doc = create_customer({"name": "Customer", "source": "wechat"})
        doc.update({"channel_contacts": {"wechat": "open-id"}, "stage": "quoted",
                    "last_message_at": "2026-11-21T10:00:00+00:00", "last_message_preview": "already answered",
                    "last_outbound_at": "2026-11-21T10:00:00+00:00", "pending_follow_up": False,
                    "next_action": "wait for current feedback"})
        save_pipeline(doc)
        growth_loop.apply_message_to_growth_loop(UnifiedMessage(
            id="newly-imported-old-event", customer_id=doc["customer_id"], channel_type="wechat",
            contact_id="open-id", contact_name="Customer", content="旧的历史问题", direction="inbound",
            created_at="2020-01-01T00:00:00+00:00", metadata={"team_id": 7},
        ))
        current = load_pipeline(doc["customer_id"])
        assert current["last_message_preview"] == "already answered"
        assert current["last_message_at"] == doc["last_message_at"]
        assert current["pending_follow_up"] is False
        assert current["next_action"] == "wait for current feedback"
