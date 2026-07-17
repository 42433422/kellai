from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request

import pytest

from app.services import xcmax_integration


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_xcmax_request_stays_on_loopback_and_marks_enterprise_client_plane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Request] = []

    def fake_urlopen(request: Request, timeout: int):
        assert timeout == 4
        captured.append(request)
        return _Response({"success": True, "data": {"state": "pending"}})

    monkeypatch.setenv("KELLAI_XCMAX_API_BASE", "http://127.0.0.1:17500")
    monkeypatch.setattr(xcmax_integration.urllib.request, "urlopen", fake_urlopen)

    payload = xcmax_integration._xcmax_request("/api/kellai/binding/pending")

    assert payload["data"]["state"] == "pending"
    assert len(captured) == 1
    request = captured[0]
    headers = {key.lower(): value for key, value in request.header_items()}
    assert request.full_url == "http://127.0.0.1:17500/api/kellai/binding/pending"
    assert headers["x-kellai-local-pairing"] == "1"
    assert headers["x-xcmax-client-shell"] == "enterprise"


def test_xcmax_base_rejects_non_loopback_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KELLAI_XCMAX_API_BASE", "https://example.com")
    with pytest.raises(RuntimeError, match="本机回环地址"):
        xcmax_integration._xcmax_base()


def test_local_connection_file_and_public_status_never_expose_access_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    xcmax_integration._write(
        {
            "version": 1,
            "connection": {
                "connection_id": "local-connection",
                "access_token": "secret-token-must-stay-local",
                "authorized_scopes": ["customer_profiles.read"],
                "authorized_by": {"id": "owner-1"},
            },
        }
    )

    stored_path = tmp_path / "integrations" / "xcmax.json"
    assert stored_path.stat().st_mode & 0o777 == 0o600
    public = xcmax_integration._public_connection(xcmax_integration._read()["connection"])
    assert public is not None
    assert "access_token" not in public
