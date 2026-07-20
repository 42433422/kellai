"""桌面 WebView 到本机后端的 CORS 与严格认证回归测试。"""

from fastapi.testclient import TestClient

from app import main


def test_strict_auth_allows_tauri_cors_preflight(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "_STRICT_AUTH", True)
    client = TestClient(main.create_app())

    response = client.options(
        "/api/kellai/channels",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_strict_auth_still_rejects_unauthed_business_request(tmp_path, monkeypatch):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "_STRICT_AUTH", True)
    client = TestClient(main.create_app())

    response = client.get("/api/kellai/channels")

    assert response.status_code == 401
    assert response.json()["error"] == "未提供认证 token"
