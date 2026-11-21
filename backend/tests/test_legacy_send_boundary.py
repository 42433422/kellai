"""Legacy endpoints must not bypass the recipient-bound sending ledger."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def legacy_client(monkeypatch, tmp_path):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KELLAI_CHANNEL_WORKER_ENABLED", "0")
    from app import main
    from app.services import auth, intake_notice, pipeline, wechat_bridge
    from app.desktop_automation import service

    monkeypatch.setattr(main, "_STRICT_AUTH", False)
    monkeypatch.setattr(auth, "verify_token", lambda token: {
        "id": 1, "team_id": 7, "role": token, "is_active": 1,
    } if token in {"owner", "readonly"} else None)
    monkeypatch.setattr(pipeline, "load_pipeline", lambda *_a, **_kw: {"customer_id": 7, "team_id": 7, "stage": "connected", "intake_submitted_at": "now"})
    monkeypatch.setattr(pipeline, "save_pipeline", lambda doc: doc)
    monkeypatch.setattr(wechat_bridge, "get_bindings_for_user", lambda *_a, **_kw: [{"name": "同名联系人"}])
    calls = []
    def record_send(*_a, **_kw):
        calls.append("legacy-name-based-send")
        return {"success": True, "message_sent": True, "sent": True}
    monkeypatch.setattr(service, "get_desktop_automation_service", lambda: SimpleNamespace(send_wechat_message=record_send))
    monkeypatch.setattr(intake_notice, "maybe_send_connected_welcome", record_send)
    monkeypatch.setattr(intake_notice, "maybe_send_intake_form_notice", record_send)
    return TestClient(main.create_app()), calls


@pytest.mark.parametrize("role", ["", "readonly", "owner"])
@pytest.mark.parametrize("path", ["send", "send-connected-welcome", "send-intake-notice"])
def test_legacy_name_based_http_send_is_closed(legacy_client, role, path):
    client, calls = legacy_client
    response = client.post(f"/api/kellai/wechat/{path}", headers={"Authorization": f"Bearer {role}"} if role else {},
                           json={"customer_id": 7, "contact_name": "同名联系人", "message": "必须经过稳定联系人和发送账本", "force": True})
    assert response.status_code in {401, 403, 409, 410}
    assert calls == [], "legacy routes must never invoke desktop sending before rejecting"


def test_analysis_does_not_send_an_implicit_welcome(legacy_client, monkeypatch):
    client, calls = legacy_client
    from app.services import pipeline, wechat_bridge
    monkeypatch.setattr(pipeline, "analyze_customer_pipeline", lambda *_a, **_kw: {"customer_id": 7, "team_id": 7, "stage": "connected"})
    monkeypatch.setattr(wechat_bridge, "build_starred_group_feed", lambda **_kw: [])
    response = client.post("/api/kellai/analyze", json={"customer_id": 7, "has_binding": True},
                           headers={"Authorization": "Bearer owner"})
    assert response.status_code == 200
    assert calls == [], "analysis is not authority for a name-only desktop message"


def test_intake_finalization_keeps_legacy_wechat_notifications_off(legacy_client, monkeypatch):
    client, _ = legacy_client
    from app.services import intake_finalize
    flags = []
    def finalize(_uid, doc, *, notify_wechat, **_kw):
        flags.append(notify_wechat)
        return doc, {"wechat_notice": {"sent": False}}
    monkeypatch.setattr(intake_finalize, "finalize_intake_submission", finalize)
    response = client.post("/api/kellai/demand-form/finalize", json={"customer_id": 7},
                           headers={"Authorization": "Bearer owner"})
    assert response.status_code == 200
    assert flags == [False]


def test_legacy_poll_cannot_pretend_to_run_live_auto_reply(legacy_client, monkeypatch):
    client, _ = legacy_client
    from app.services import passive_monitor
    calls = []
    def poll(**_kw):
        calls.append(True)
        return {"success": True, "replies": [{"reply_source": "llm_stub", "reply": "fake"}]}
    monkeypatch.setattr(passive_monitor, "passive_poll_once", poll)
    response = client.post("/api/kellai/wechat/passive-poll", json={"customer_id": 7, "dry_run": False, "auto_reply": True},
                           headers={"Authorization": "Bearer owner"})
    assert response.status_code in {409, 410}
    assert calls == []


def test_desktop_wechat_service_cannot_be_reenabled_as_an_untracked_bypass(monkeypatch):
    from app.desktop_automation.service import DesktopAutomationService
    monkeypatch.setenv("KELLAI_WECHAT_AUTOMATION", "1")
    service = DesktopAutomationService()
    attempts = []
    service._automation = SimpleNamespace(_connected=True,
        send_text_message=lambda *args: attempts.append(args) or {"success": True, "message_sent": True})
    result = service.send_wechat_message("同名联系人", "必须走统一发送边界")
    assert result["success"] is False and result["message_sent"] is False
    assert attempts == []


@pytest.mark.parametrize(("endpoint", "body"), [
    ("/api/kellai/content/publish", {"content_id": "draft", "platforms": ["douyin"]}),
    ("/api/kellai/scout/auto-dm", {"target_id": "st1", "message": "not a verified recipient"}),
])
def test_unimplemented_external_actions_do_not_report_success(legacy_client, endpoint, body):
    client, _ = legacy_client
    from app.api.scout import _TARGETS
    original_status = _TARGETS[0]["status"]
    response = client.post(endpoint, json=body, headers={"Authorization": "Bearer owner"})
    assert response.status_code == 501
    assert _TARGETS[0]["status"] == original_status
