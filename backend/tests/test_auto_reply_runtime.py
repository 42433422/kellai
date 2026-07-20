from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.channels.base import UnifiedMessage
from app.services import ai_copilot, auto_reply_runtime, llm_config, message_store, pipeline


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
    monkeypatch.setattr(auto_reply_runtime, "_crm_db_path", lambda: db_path)
    monkeypatch.setattr(
        llm_config,
        "public_config",
        lambda: {
            "autoReplyEnabled": True,
            "autoReplyStages": ["connected"],
            "confirmScenarios": list(confirm_scenarios or []),
        },
    )
    monkeypatch.setattr(pipeline, "load_pipeline", lambda _customer_id: {"stage": "connected"})
    monkeypatch.setattr(message_store, "get_messages", lambda *_args, **_kwargs: [])
    return db_path


def _make_available(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE kellai_auto_reply_jobs SET available_at=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
        )
        conn.commit()


def test_auto_reply_job_is_deduplicated_claimed_and_completed(monkeypatch, tmp_path):
    db_path = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ai_copilot,
        "generate_auto_reply",
        lambda *_args, **_kwargs: {
            "draft": "您好，很高兴为您服务。",
            "can_auto_send": True,
            "reason": "",
        },
    )

    message = _message()
    assert auto_reply_runtime.enqueue_message(message) is True
    assert auto_reply_runtime.enqueue_message(message) is False
    _make_available(db_path)

    jobs = auto_reply_runtime.claim_jobs(team_id=3, limit=3)
    assert len(jobs) == 1
    assert jobs[0]["reply_content"] == "您好，很高兴为您服务。"
    assert jobs[0]["contact_name"] == "真实客户"

    assert auto_reply_runtime.complete_job(
        "inbound-1",
        success=True,
        outbound_message_id="outbound-1",
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
            "reason": "",
        },
    )

    assert auto_reply_runtime.enqueue_message(
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
            "reason": "",
        },
    )
    assert auto_reply_runtime.enqueue_message(_message()) is True
    _make_available(db_path)
    assert len(auto_reply_runtime.claim_jobs(team_id=3, limit=1)) == 1

    assert auto_reply_runtime.complete_job(
        "inbound-1",
        success=False,
        error="不应该跨团队修改",
        team_id=4,
    ) is False
    assert auto_reply_runtime.runtime_status(team_id=3)["latest"]["status"] == "processing"
    assert auto_reply_runtime.complete_job(
        "inbound-1",
        success=True,
        outbound_message_id="outbound-1",
        team_id=3,
    ) is True
