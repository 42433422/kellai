"""v3-v8 新增 API 桩路由冒烟测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


class TestSalesAPI:
    def test_performance(self, client):
        r = client.get("/api/kellai/sales/performance")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_auto_flow(self, client):
        r = client.post("/api/kellai/sales/auto-flow", json={"customer_id": 1001})
        assert r.status_code == 200
        assert r.json()["data"]["customer_id"] == 1001

    def test_ltv(self, client):
        r = client.get("/api/kellai/sales/ltv/1001")
        assert r.status_code == 200
        assert "predicted_ltv" in r.json()["data"]


class TestContentAPI:
    def test_analytics(self, client):
        r = client.get("/api/kellai/content/analytics")
        assert r.status_code == 200


class TestScoutAPI:
    def test_sentiment(self, client):
        r = client.get("/api/kellai/scout/sentiment")
        assert r.status_code == 200


class TestFlowAPI:
    def test_templates(self, client):
        r = client.get("/api/kellai/flow/templates")
        assert r.status_code == 200
        assert len(r.json()["data"]) >= 1


class TestFinanceAPI:
    def test_dashboard(self, client):
        r = client.get("/api/kellai/finance/dashboard")
        assert r.status_code == 200
        assert r.json()["data"]["revenue"] > 0


class TestOpenAPI:
    def test_plugins(self, client):
        r = client.get("/api/kellai/open/plugins")
        assert r.status_code == 200

    def test_docs(self, client):
        r = client.get("/api/kellai/open/docs")
        assert r.status_code == 200
        assert "endpoints" in r.json()["data"]

    def test_open_platform_state_persists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
        from app.api import open as open_api

        created = open_api.create_key(
            open_api.KeyBody(name="Smoke", scopes=["customers:read", "messages:write"])
        )["data"]
        assert created["api_key"].startswith("kl_live_")
        assert created["key_prefix"].endswith("****")
        keys = open_api.api_keys()["data"]
        assert len(keys) == 1
        assert keys[0]["name"] == "Smoke"
        assert "api_key" not in keys[0]

        webhook = open_api.webhooks(
            open_api.WebhookBody(url="https://example.com/kellai", events=["customer.created"])
        )["data"]
        assert webhook["secret"].startswith("whsec_")
        assert open_api.list_webhooks()["data"][0]["url"] == "https://example.com/kellai"

        assert open_api.install_plugin({"plugin_id": "p2"})["data"]["installed"] is True
        installed = {p["id"]: p["installed"] for p in open_api.plugins()["data"]}
        assert installed["p2"] is True
