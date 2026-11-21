"""Worker ownership and transport routing with real inbox/queue/outbox state."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.channels import ChannelRegistry, config_store
from app.channels.douyin import DouyinAdapter
from app.channels.wecom import WeComAdapter
from app.services import auto_reply_runtime, channel_worker, message_store
from app.services.tenant_context import current_team_id, tenant_scope


@pytest.fixture
def worker(monkeypatch, tmp_path):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KELLAI_APP_ENV", "development")
    monkeypatch.setenv("KELLAI_CHANNEL_WORKER_ENABLED", "0")
    for key in (
        "KELLAI_CHANNEL_CONFIG_PATH", "KELLAI_DOUYIN_BRIDGE_KEY", "KELLAI_WECOM_BRIDGE_KEY",
        "KELLAI_DOUYIN_REMOTE_BASE_URL", "KELLAI_DOUYIN_REMOTE_BRIDGE_KEY",
        "KELLAI_DOUYIN_DESKTOP_AUTOMATION",
    ):
        monkeypatch.delenv(key, raising=False)
    from app.services import ai_copilot, auth, crm_store, douyin_channel

    importlib.reload(crm_store)
    importlib.reload(auth)
    account = auth.register_user(email="worker@example.test", password="TestWorkerSecret123!",
                                 display_name="Worker owner")
    assert account["success"]
    team_id = int(account["user"]["team_id"])
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(auto_reply_runtime, "_now", lambda: clock[0])
    monkeypatch.setattr(auto_reply_runtime, "_enabled_config", lambda: {
        "autoReplyEnabled": True, "autoReplyStages": [], "confirmScenarios": [],
    })
    monkeypatch.setattr(douyin_channel, "remote_bridge_enabled", lambda: False)
    monkeypatch.setattr("app.channels.douyin.remote_bridge_enabled", lambda: False)
    drafts, sends = [], []

    def generate_reply(*args, **kwargs):
        drafts.append((args, kwargs))
        return {"draft": "您好，需要了解哪项服务？", "can_auto_send": True,
                "generation_source": "llm"}

    async def isolated_send(contact_id, content, **kwargs):
        sends.append((current_team_id(), contact_id, content, kwargs))
        return {"success": True, "message_id": f"provider-{len(sends)}", "delivery_state": "accepted"}

    monkeypatch.setattr(ai_copilot, "generate_auto_reply", generate_reply)
    douyin, wework = DouyinAdapter(), WeComAdapter()
    monkeypatch.setattr(douyin, "send_message", isolated_send)
    monkeypatch.setattr(wework, "send_message", isolated_send)
    original_get = ChannelRegistry.get
    monkeypatch.setattr(ChannelRegistry, "get", lambda registry, kind:
                        {"douyin": douyin, "wework": wework}.get(kind) or original_get(registry, kind))
    with tenant_scope(team_id):
        config_store.save("douyin", {}, enabled=True)
        config_store.save("wework", {}, enabled=False)

    def put(message_id: str, *, contact_id: str = "official-contact", native: bool = False,
            channel: str = "douyin"):
        with tenant_scope(team_id):
            return message_store.push_inbox(
                channel, contact_id=contact_id, contact_name=contact_id, direction="inbound",
                content="请介绍一下服务", msg_id=message_id,
                metadata={"team_id": team_id, "source": "douyin_web_portal" if native else "official_webhook"},
            )

    def jobs():
        auto_reply_runtime.ensure_schema()
        with sqlite3.connect(str(tmp_path / "kellai.db")) as connection:
            return connection.execute(
                "SELECT inbound_message_id, status, attempts FROM kellai_auto_reply_jobs WHERE team_id=?",
                (team_id,),
            ).fetchall()

    return SimpleNamespace(team_id=team_id, clock=clock, drafts=drafts, sends=sends, put=put,
                           jobs=jobs, tmp_path=tmp_path)


@pytest.mark.parametrize("bridge_setting", ["KELLAI_DOUYIN_BRIDGE_KEY", "KELLAI_WECOM_BRIDGE_KEY"])
def test_bridge_relay_preserves_downstream_inbox_and_leaves_other_channels_running(worker, monkeypatch, bridge_setting):
    from app.services.douyin_channel import pull_team_inbox

    monkeypatch.setenv(bridge_setting, "isolated-relay-key")
    worker.put("relay-douyin-inbound")
    worker.put("local-wework-inbound", channel="wework", contact_id="member-one")
    with tenant_scope(worker.team_id):
        config_store.save("wework", {}, enabled=True)
    assert len(pull_team_inbox(worker.team_id)) == 1
    first = asyncio.run(channel_worker.run_once())
    assert first == {"tenants": 1, "jobs": 0, "errors": 0}
    assert [row["id"] for row in pull_team_inbox(worker.team_id)] == ["relay-douyin-inbound"]
    assert {row[0] for row in worker.jobs()} == {"local-wework-inbound"}
    worker.clock[0] += timedelta(seconds=4)
    second = asyncio.run(channel_worker.run_once())
    assert second["jobs"] == 1 and second["errors"] == 0
    assert worker.sends[0][1] == "member-one"
    assert len(pull_team_inbox(worker.team_id)) == 1


def test_hybrid_official_douyin_job_completes_without_a_desktop_worker(worker):
    worker.put("official-inbound")
    assert asyncio.run(channel_worker.run_once())["jobs"] == 0  # Queue debounce.
    worker.clock[0] += timedelta(seconds=4)
    result = asyncio.run(channel_worker.run_once())
    assert result == {"tenants": 1, "jobs": 1, "errors": 0}
    assert len(worker.sends) == 1 and worker.sends[0][1] == "official-contact"
    assert worker.jobs() == [("official-inbound", "sent", 1)]
    from app.services.outbound_delivery import get_delivery

    receipt = get_delivery("auto:official-inbound", team_id=worker.team_id)
    assert receipt["persisted"] and receipt["provider_message_id"] == "provider-1"
    assert receipt["provider_state"] == "accepted"
    assert asyncio.run(channel_worker.run_once())["jobs"] == 0
    assert len(worker.sends) == 1


def test_relay_does_not_dispatch_preexisting_local_douyin_jobs(worker, monkeypatch):
    worker.put("queued-before-relay-role")
    asyncio.run(channel_worker.run_once())
    monkeypatch.setenv("KELLAI_DOUYIN_BRIDGE_KEY", "isolated-relay-key")
    worker.clock[0] += timedelta(seconds=4)
    result = asyncio.run(channel_worker.run_once())
    assert result == {"tenants": 1, "jobs": 0, "errors": 0}
    assert worker.jobs() == [("queued-before-relay-role", "pending", 0)]
    assert not worker.sends and not worker.drafts


def test_hybrid_native_job_remains_unclaimed_while_api_job_sends(worker):
    worker.put("native-inbound", contact_id="portal-contact", native=True)
    worker.put("official-inbound")
    asyncio.run(channel_worker.run_once())
    worker.clock[0] += timedelta(seconds=4)
    result = asyncio.run(channel_worker.run_once())
    assert result["jobs"] == 1 and result["errors"] == 0
    assert {row[0]: row[1:] for row in worker.jobs()} == {
        "native-inbound": ("pending", 0), "official-inbound": ("sent", 1),
    }
    assert [call[1] for call in worker.sends] == ["official-contact"]
    assert len(worker.drafts) == 1, "The server must not generate or lease a native draft."
    native = auto_reply_runtime.claim_jobs(team_id=worker.team_id, channel_types=["douyin"], transport="desktop")
    assert [job["inbound_message_id"] for job in native] == ["native-inbound"]
    assert asyncio.run(channel_worker.run_once())["jobs"] == 0
    assert len(worker.sends) == 1


def test_worker_reports_ingest_failure_and_leaves_inbox_replayable(worker, monkeypatch):
    worker.put("queue-failure-inbound")

    def fail_enqueue(_message):
        raise sqlite3.OperationalError("fixture queue temporarily unavailable")

    monkeypatch.setattr(auto_reply_runtime, "enqueue_message", fail_enqueue)
    result = asyncio.run(channel_worker.run_once())
    assert result == {"tenants": 1, "jobs": 0, "errors": 1}
    with tenant_scope(worker.team_id):
        assert [row["id"] for row in message_store.list_inbox("douyin")] == ["queue-failure-inbound"]
    assert not worker.sends
