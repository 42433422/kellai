from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.channels.base import UnifiedMessage
from app.services import ai_copilot, auto_reply_runtime, llm_config, message_store, outbound_delivery, pipeline


def _message(*, message_id: str = "inbound-1", content: str = "你好") -> UnifiedMessage:
    return UnifiedMessage(
        id=message_id,
        customer_id=7,
        channel_type="douyin",
        contact_id="contact-7",
        contact_name="真实客户",
        direction="inbound",
        content=content,
        content_type="text",
        metadata={"team_id": 3},
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _prepare(monkeypatch, tmp_path, *, confirm_scenarios=None):
    db_path = tmp_path / "auto-reply.db"
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(auto_reply_runtime, "_crm_db_path", lambda: db_path)
    monkeypatch.setattr(outbound_delivery, "_crm_db_path", lambda: db_path)
    monkeypatch.setattr(message_store, "_crm_db_path", lambda: db_path)
    from app.services import growth_loop, workforce_routing

    monkeypatch.setattr(growth_loop, "apply_message_to_growth_loop", lambda _msg: {})
    monkeypatch.setattr(workforce_routing, "touch_assignment", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        llm_config,
        "public_config",
        lambda: {
            "autoReplyEnabled": True,
            "autoReplyStages": ["connected"],
            "confirmScenarios": list(confirm_scenarios or []),
        },
    )
    from app.services import crm_store
    from app.services.tenant_context import tenant_scope
    monkeypatch.setattr(crm_store, "_crm_db_path", lambda: db_path)
    with tenant_scope(3):
        doc = pipeline.load_pipeline(7)
        doc.update(stage="connected", username="真实客户", channel_contacts={"douyin": "contact-7"})
        pipeline.save_pipeline(doc)
    monkeypatch.setattr(message_store, "get_messages", lambda *_args, **_kwargs: [])
    return db_path


def _enqueue(message):
    return auto_reply_runtime.enqueue_message(message_store.save_message(message))


def _make_available(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE kellai_auto_reply_jobs SET available_at=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
        )
        conn.commit()


def _begin(job):
    return auto_reply_runtime.begin_delivery(
        job["inbound_message_id"], lease_token=job["lease_token"], team_id=3,
        customer_id=job["customer_id"], channel_type=job["channel_type"],
        contact_id=job["contact_id"], content=job["reply_content"],
    )


def _record_delivery(job, *, success=True):
    assert _begin(job)
    outgoing = UnifiedMessage(
        id="temporary", customer_id=job["customer_id"], channel_type=job["channel_type"],
        contact_id=job["contact_id"], contact_name=job["contact_name"],
        direction="outbound", content=job["reply_content"],
        metadata={"team_id": 3, "auto_reply_inbound_id": job["inbound_message_id"]},
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    reserved = outbound_delivery.prepare_external(outgoing, idempotency_key=job["delivery_key"], team_id=3)
    return outbound_delivery.complete_external(
        idempotency_key=job["delivery_key"], delivery_token=reserved["delivery_token"],
        team_id=3, result={"success": success, "message_id": "platform-1"} if success else {
            "success": False, "delivery_state": "unknown", "error": "timeout"
        },
    )


def test_auto_reply_job_is_deduplicated_claimed_and_completed(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ai_copilot,
        "generate_auto_reply",
        lambda *_args, **_kwargs: {
            "draft": "您好，很高兴为您服务。",
            "can_auto_send": True,
            "generation_source": "llm",
            "reason": "",
        },
    )

    message = _message()
    assert _enqueue(message) is True
    assert _enqueue(message) is False
    _make_available(db_path)

    jobs = auto_reply_runtime.claim_jobs(team_id=3, limit=3)
    assert len(jobs) == 1
    assert jobs[0]["reply_content"] == "您好，很高兴为您服务。"
    assert jobs[0]["contact_name"] == "真实客户"
    receipt = _record_delivery(jobs[0])

    assert auto_reply_runtime.complete_job(
        "inbound-1",
        success=True,
        outbound_message_id=receipt["message_id"],
        lease_token=jobs[0]["lease_token"],
        team_id=3,
    ) is True
    status = auto_reply_runtime.runtime_status(team_id=3)
    assert status["counts"]["sent"] == 1
    assert status["latest"]["status"] == "sent"


def test_sensitive_message_uses_safe_confirmation(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path, confirm_scenarios=["涉及价格"])
    monkeypatch.setattr(
        ai_copilot,
        "generate_auto_reply",
        lambda *_args, **_kwargs: {
            "draft": "我们保证这是最低价格。",
            "can_auto_send": True,
            "generation_source": "llm",
            "reason": "",
        },
    )

    assert _enqueue(
        _message(message_id="inbound-price", content="请问具体价格是多少？")
    ) is True
    _make_available(db_path)
    jobs = auto_reply_runtime.claim_jobs(team_id=3, limit=1)

    assert jobs[0]["reply_content"] == auto_reply_runtime.SAFE_CONFIRMATION_REPLY
    assert jobs[0]["policy_reason"] == "涉及价格"


def test_job_completion_is_team_scoped(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ai_copilot,
        "generate_auto_reply",
        lambda *_args, **_kwargs: {
            "draft": "您好，很高兴为您服务。",
            "can_auto_send": True,
            "generation_source": "llm",
            "reason": "",
        },
    )
    assert _enqueue(_message()) is True
    _make_available(db_path)
    jobs = auto_reply_runtime.claim_jobs(team_id=3, limit=1)
    assert len(jobs) == 1
    receipt = _record_delivery(jobs[0])

    assert auto_reply_runtime.complete_job(
        "inbound-1",
        success=False,
        error="不应该跨团队修改",
        team_id=4,
        lease_token=jobs[0]["lease_token"],
    ) is False
    assert auto_reply_runtime.runtime_status(team_id=3)["latest"]["status"] == "sending"
    assert auto_reply_runtime.complete_job(
        "inbound-1",
        success=True,
        outbound_message_id=receipt["message_id"],
        lease_token=jobs[0]["lease_token"],
        team_id=3,
    ) is True


def _claim_one(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_copilot, "generate_auto_reply", lambda *_a, **_kw: {"draft": "已收到您的需求", "can_auto_send": True, "generation_source": "llm"})
    assert _enqueue(_message())
    _make_available(db_path)
    return db_path, auto_reply_runtime.claim_jobs(team_id=3)[0]


def test_bare_success_flag_cannot_complete_without_provider_receipt(monkeypatch, tmp_path):
    _, job = _claim_one(monkeypatch, tmp_path)
    assert not auto_reply_runtime.complete_job("inbound-1", success=True, team_id=3,
                                              lease_token=job["lease_token"], outbound_message_id="invented")
    assert auto_reply_runtime.runtime_status(team_id=3)["latest"]["status"] == "processing"


def test_old_worker_cannot_send_or_complete_a_new_lease(monkeypatch, tmp_path):
    db_path, first = _claim_one(monkeypatch, tmp_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("UPDATE kellai_auto_reply_jobs SET lease_until=?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))
    second = auto_reply_runtime.claim_jobs(team_id=3)[0]
    assert second["lease_token"] != first["lease_token"]
    assert not _begin(first)
    assert not auto_reply_runtime.complete_job("inbound-1", success=False, team_id=3, lease_token=first["lease_token"])
    assert _begin(second)


def test_unknown_send_is_not_reclaimed_or_superseded(monkeypatch, tmp_path):
    db_path, job = _claim_one(monkeypatch, tmp_path)
    receipt = _record_delivery(job, success=False)
    assert receipt["status"] == "unknown"
    assert auto_reply_runtime.complete_job("inbound-1", success=False, team_id=3, lease_token=job["lease_token"])
    assert _enqueue(_message(message_id="inbound-2"))
    _make_available(db_path)
    assert auto_reply_runtime.claim_jobs(team_id=3) == []
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"unknown": 1, "pending": 1}


def test_lost_worker_report_reconciles_without_new_send(monkeypatch, tmp_path):
    _, job = _claim_one(monkeypatch, tmp_path)
    receipt = _record_delivery(job)
    assert receipt["persisted"]
    # No complete_job call: the desktop disappeared after backend persistence.
    assert auto_reply_runtime.claim_jobs(team_id=3) == []
    status = auto_reply_runtime.runtime_status(team_id=3)
    assert status["counts"] == {"sent": 1}


def test_cancelled_draft_cannot_be_revived_by_its_worker(monkeypatch, tmp_path):
    _, job = _claim_one(monkeypatch, tmp_path)
    assert auto_reply_runtime.cancel_job("inbound-1", team_id=3)
    assert not _begin(job)
    assert not auto_reply_runtime.complete_job("inbound-1", success=False, team_id=3, lease_token=job["lease_token"])
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"cancelled": 1}


def test_sending_work_cannot_be_cancelled_as_if_unsent(monkeypatch, tmp_path):
    _, job = _claim_one(monkeypatch, tmp_path)
    assert _begin(job)
    assert not auto_reply_runtime.cancel_job("inbound-1", team_id=3)


def test_begin_delivery_binds_reply_recipient_and_customer(monkeypatch, tmp_path):
    _, job = _claim_one(monkeypatch, tmp_path)
    for field, wrong in [("customer_id", 99), ("contact_id", "other"), ("channel_type", "telegram"), ("reply_content", "unauthorized text")]:
        assert not _begin({**job, field: wrong})
    assert _begin(job)


def test_model_failure_retries_drafting_without_sending_fabricated_reply(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path)

    def fail(*_a, **_kw):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(ai_copilot, "generate_auto_reply", fail)
    assert _enqueue(_message())
    _make_available(db_path)
    assert auto_reply_runtime.claim_jobs(team_id=3) == []
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"failed": 1}
    monkeypatch.setattr(ai_copilot, "generate_auto_reply", lambda *_a, **_kw: {"draft": "恢复后的草稿", "can_auto_send": True, "generation_source": "llm"})
    _make_available(db_path)
    assert auto_reply_runtime.claim_jobs(team_id=3)[0]["reply_content"] == "恢复后的草稿"


def test_legacy_processing_without_fence_is_migrated_to_unknown(monkeypatch, tmp_path):
    db_path, _ = _claim_one(monkeypatch, tmp_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("UPDATE kellai_auto_reply_jobs SET lease_token='', lease_until='2000-01-01'")
    assert auto_reply_runtime.claim_jobs(team_id=3) == []
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"unknown": 1}


def test_late_failure_does_not_downgrade_accepted_delivery(monkeypatch, tmp_path):
    _, job = _claim_one(monkeypatch, tmp_path)
    receipt = _record_delivery(job)
    assert auto_reply_runtime.complete_job("inbound-1", success=True, team_id=3, lease_token=job["lease_token"], outbound_message_id=receipt["message_id"])
    assert auto_reply_runtime.complete_job("inbound-1", success=False, team_id=3, lease_token=job["lease_token"], error="lost HTTP response")
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"sent": 1}


def test_native_and_api_workers_claim_only_their_channel_types(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_copilot, "generate_auto_reply", lambda *_a, **_kw: {"draft": "真实模型草稿", "can_auto_send": True, "generation_source": "llm"})
    assert _enqueue(_message())
    assert _enqueue(_message(message_id="api-message").model_copy(update={"channel_type": "telegram"}))
    _make_available(db_path)
    assert auto_reply_runtime.claim_jobs(team_id=3, channel_types=[]) == []
    native = auto_reply_runtime.claim_jobs(team_id=3, channel_types=["douyin"])
    server = auto_reply_runtime.claim_jobs(team_id=3, channel_types=["telegram"])
    assert [job["channel_type"] for job in native] == ["douyin"]
    assert [job["channel_type"] for job in server] == ["telegram"]


def test_template_fallback_is_not_sent_as_model_output(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_copilot, "generate_auto_reply", lambda *_a, **_kw: {"draft": "模板回复", "can_auto_send": True, "generation_source": "template"})
    assert _enqueue(_message())
    _make_available(db_path)
    assert auto_reply_runtime.claim_jobs(team_id=3) == []
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"failed": 1}


def test_empty_or_unparsed_media_stays_out_of_text_auto_reply(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    assert not auto_reply_runtime.enqueue_message(_message(content=" "))
    for kind in ("file", "image", "audio", "video", "event"):
        assert not auto_reply_runtime.enqueue_message(_message().model_copy(update={"content_type": kind}))
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {}


@pytest.mark.parametrize("changes", [
    {"created_at": "2020-01-01T00:00:00+00:00"},
    {"metadata": {"team_id": 3, "provider_created_at": 1_577_836_800}},
    {"metadata": {"team_id": 3, "provider_created_at": None}},
    {"metadata": {"team_id": 3, "historical": True}},
    {"metadata": {"team_id": 3, "history_backfill": "true"}},
    {"metadata": {"team_id": 3, "simulated": True}},
    {"metadata": {"team_id": 3, "is_demo": "yes"}},
    {"metadata": {"team_id": 3, "source": "closed_loop_audit"}},
])
def test_historical_simulated_and_untrusted_timestamps_do_not_enqueue(monkeypatch, tmp_path, changes):
    _prepare(monkeypatch, tmp_path)
    assert not _enqueue(_message().model_copy(update=changes))
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {}


def test_future_provider_time_is_not_a_live_inbound(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    assert not _enqueue(_message().model_copy(update={"created_at": future}))


def test_enqueue_requires_existing_real_customer_and_persisted_message(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    from app.services.tenant_context import tenant_scope
    assert not auto_reply_runtime.enqueue_message(_message())
    with tenant_scope(3):
        doc = pipeline.load_pipeline(7)
        doc["is_demo"] = True
        pipeline.save_pipeline(doc)
    assert not _enqueue(_message())
    with tenant_scope(3):
        pipeline._pipeline_file(7).unlink()
    assert not _enqueue(_message())
    with tenant_scope(3):
        assert not pipeline._pipeline_file(7).exists()


def test_all_twenty_messages_are_ranked_before_worker_limit(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_copilot, "generate_auto_reply", lambda *_a, **_kw: {"draft": "收到", "generation_source": "llm"})
    start = datetime.now(timezone.utc) - timedelta(seconds=30)
    for number in range(20):
        assert _enqueue(_message(message_id=f"in{number}").model_copy(update={"created_at": (start + timedelta(seconds=number)).isoformat()}))
    _make_available(db_path)
    claimed = auto_reply_runtime.claim_jobs(team_id=3, limit=3)
    assert [item["inbound_message_id"] for item in claimed] == ["in19"]
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"processing": 1, "superseded": 19}
    assert auto_reply_runtime.claim_jobs(team_id=3, limit=3) == []


def test_newer_debounced_message_prevents_reply_to_older_due_message(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path)
    assert _enqueue(_message(message_id="older"))
    _make_available(db_path)
    assert _enqueue(_message(message_id="newer"))
    assert auto_reply_runtime.claim_jobs(team_id=3) == []
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"pending": 1, "superseded": 1}


@pytest.mark.parametrize("direction", ["inbound", "outbound"])
def test_message_arriving_during_model_generation_invalidates_draft(monkeypatch, tmp_path, direction):
    db_path = _prepare(monkeypatch, tmp_path)
    assert _enqueue(_message())
    _make_available(db_path)

    def generate(*_a, **_kw):
        # The incoming message need not have an auto job (e.g. an attachment,
        # or a customer reply whose own enqueue has not happened yet).
        newer = _message(message_id="arrived-while-drafting").model_copy(update={"direction": direction})
        message_store.save_message(newer)
        return {"draft": "已过时的回复", "generation_source": "llm"}

    monkeypatch.setattr(ai_copilot, "generate_auto_reply", generate)
    assert auto_reply_runtime.claim_jobs(team_id=3) == []
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"superseded": 1}


@pytest.mark.parametrize("direction", ["inbound", "outbound"])
def test_message_arriving_after_draft_before_send_fences_worker(monkeypatch, tmp_path, direction):
    _, job = _claim_one(monkeypatch, tmp_path)
    message_store.save_message(_message(message_id="newer-message").model_copy(update={"direction": direction}))
    assert not _begin(job)
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"superseded": 1}
    assert not auto_reply_runtime.complete_job("inbound-1", success=False, team_id=3, lease_token=job["lease_token"])


@pytest.mark.parametrize("change", ["signed", "deleted", "demo"])
def test_begin_rereads_customer_instead_of_enqueued_stage(monkeypatch, tmp_path, change):
    _, job = _claim_one(monkeypatch, tmp_path)
    from app.services.tenant_context import tenant_scope
    with tenant_scope(3):
        if change == "deleted":
            pipeline._pipeline_file(7).unlink()
        else:
            doc = pipeline.load_pipeline(7)
            if change == "demo":
                doc["is_demo"] = True
            else:
                doc["stage"] = change
            pipeline.save_pipeline(doc)
    assert not _begin(job)
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"cancelled": 1}
    if change == "deleted":
        with tenant_scope(3):
            assert not pipeline._pipeline_file(7).exists()


def test_draft_expires_from_original_message_time_not_retry_time(monkeypatch, tmp_path):
    db_path, job = _claim_one(monkeypatch, tmp_path)
    assert auto_reply_runtime.complete_job("inbound-1", success=False, team_id=3, lease_token=job["lease_token"], error="temporary")
    _make_available(db_path)
    later = datetime.now(timezone.utc) + timedelta(seconds=auto_reply_runtime.REALTIME_REPLY_WINDOW_SECONDS + 1)
    monkeypatch.setattr(auto_reply_runtime, "_now", lambda: later)
    assert auto_reply_runtime.claim_jobs(team_id=3) == []
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"expired": 1}


def test_unknown_delivery_is_not_expired_or_retried(monkeypatch, tmp_path):
    _, job = _claim_one(monkeypatch, tmp_path)
    receipt = _record_delivery(job, success=False)
    assert receipt["status"] == "unknown"
    assert auto_reply_runtime.complete_job("inbound-1", success=False, team_id=3, lease_token=job["lease_token"])
    later = datetime.now(timezone.utc) + timedelta(days=2)
    monkeypatch.setattr(auto_reply_runtime, "_now", lambda: later)
    assert auto_reply_runtime.claim_jobs(team_id=3) == []
    assert auto_reply_runtime.runtime_status(team_id=3)["counts"] == {"unknown": 1}


def test_parallel_workers_only_lease_one_latest_conversation_job(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    db_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_copilot, "generate_auto_reply", lambda *_a, **_kw: {"draft": "唯一草稿", "generation_source": "llm"})
    assert _enqueue(_message())
    _make_available(db_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(auto_reply_runtime.claim_jobs, team_id=3) for _ in range(2)]
        jobs = [job for future in futures for job in future.result()]
    assert len(jobs) == 1
    assert jobs[0]["attempt"] == 1


def test_upgrade_keeps_retry_window_from_persisted_original_time(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_copilot, "generate_auto_reply", lambda *_a, **_kw: {"draft": "升级后继续", "generation_source": "llm"})
    provider_at = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    assert _enqueue(_message().model_copy(update={"metadata": {"team_id": 3, "provider_created_at": provider_at}}))
    _make_available(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("ALTER TABLE kellai_auto_reply_jobs DROP COLUMN inbound_at")
    jobs = auto_reply_runtime.claim_jobs(team_id=3)
    assert len(jobs) == 1
    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute("SELECT inbound_at FROM kellai_auto_reply_jobs").fetchone()[0] == provider_at
