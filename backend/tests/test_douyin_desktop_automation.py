from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("KELLAI_APP_ENV", "development")
os.environ.setdefault("KELLAI_JWT_SECRET", "test-secret-for-pytest-only")
os.environ.setdefault("KELLAI_PASSWORD_SALT", "test-salt-for-pytest-only")

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def automation(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    from app.services import crm_store, douyin_desktop_automation

    importlib.reload(crm_store)
    module = importlib.reload(douyin_desktop_automation)
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    return module


def test_same_contact_reuses_cached_conversation(automation, monkeypatch):
    scripts: list[str] = []

    def fake_run(**kwargs):
        scripts.append(str(kwargs["reuse_cached_conversation"]))
        return "prepared|false" if len(scripts) == 1 else "prepared|true"

    monkeypatch.setattr(automation, "_execute_flow", fake_run)

    first = automation.send_message(
        contact_name="客户甲",
        contact_id="open-1",
        content="第一次",
        prepare_only=True,
    )
    second = automation.send_message(
        contact_name="客户甲",
        contact_id="open-1",
        content="第二次",
        prepare_only=True,
    )

    assert first["success"] is True
    assert second["reused_conversation"] is True
    assert scripts == ["False", "True"]


def test_different_contact_forces_search_path(automation, monkeypatch):
    scripts: list[str] = []
    monkeypatch.setattr(
        automation,
        "_execute_flow",
        lambda **kwargs: scripts.append(str(kwargs["reuse_cached_conversation"]))
        or "prepared|false",
    )

    automation.send_message(
        contact_name="客户甲",
        contact_id="open-1",
        content="第一条",
        prepare_only=True,
    )
    automation.send_message(
        contact_name="客户乙",
        contact_id="open-2",
        content="第二条",
        prepare_only=True,
    )

    assert scripts[1] == "False"


def test_automation_error_is_returned_to_api_layer(automation, monkeypatch):
    def fail(**_kwargs):
        raise automation.DouyinDesktopAutomationError("没有辅助功能权限")

    monkeypatch.setattr(automation, "_execute_flow", fail)
    result = automation.send_message(contact_name="客户甲", content="你好")

    assert result["success"] is False
    assert "辅助功能权限" in result["error"]


@pytest.mark.parametrize(
    ("current_matches", "expected_reuse"),
    [(True, "true"), (False, "false")],
)
def test_cached_conversation_is_verified_against_visible_header(
    automation,
    monkeypatch,
    current_matches,
    expected_reuse,
):
    calls: list[str] = []
    monkeypatch.setattr(automation, "_raise_main_window", lambda: None)
    monkeypatch.setattr(
        automation,
        "_main_window_bounds",
        lambda: {"X": 0.0, "Y": 0.0, "Width": 1000.0, "Height": 700.0},
    )
    match_results = iter([True] if current_matches else [False, True])
    monkeypatch.setattr(
        automation,
        "_current_conversation_matches",
        lambda **_kwargs: next(match_results),
    )
    monkeypatch.setattr(
        automation,
        "_ensure_message_panel",
        lambda _coordinates: calls.append("panel"),
    )
    monkeypatch.setattr(
        automation,
        "_open_contact_from_search",
        lambda **_kwargs: calls.append("search"),
    )
    monkeypatch.setattr(
        automation,
        "_fill_and_maybe_send",
        lambda **_kwargs: calls.append("fill") or "prepared",
    )

    result = automation._execute_flow(
        contact_name="客户甲",
        content="你好",
        reuse_cached_conversation=True,
        prepare_only=True,
    )

    assert result == f"prepared|{expected_reuse}"
    assert calls == (["panel", "fill"] if current_matches else ["panel", "search", "fill"])


def test_search_must_open_the_requested_contact_before_filling(automation, monkeypatch):
    monkeypatch.setattr(automation, "_raise_main_window", lambda: None)
    monkeypatch.setattr(
        automation,
        "_main_window_bounds",
        lambda: {"X": 0.0, "Y": 0.0, "Width": 1000.0, "Height": 700.0},
    )
    monkeypatch.setattr(automation, "_ensure_message_panel", lambda _coordinates: None)
    monkeypatch.setattr(automation, "_open_contact_from_search", lambda **_kwargs: None)
    monkeypatch.setattr(automation, "_current_conversation_matches", lambda **_kwargs: False)
    fill_calls: list[str] = []
    monkeypatch.setattr(
        automation,
        "_fill_and_maybe_send",
        lambda **_kwargs: fill_calls.append("fill") or "prepared",
    )
    monkeypatch.setattr(automation.time, "sleep", lambda _seconds: None)

    with pytest.raises(automation.DouyinDesktopAutomationError, match="已取消发送"):
        automation._execute_flow(
            contact_name="不存在的用户",
            content="你好",
            reuse_cached_conversation=False,
            prepare_only=True,
        )

    assert fill_calls == []
