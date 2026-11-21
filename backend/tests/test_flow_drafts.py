"""Graph drafts are durable and tenant-scoped, without invented executions."""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def product(monkeypatch, tmp_path):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KELLAI_CHANNEL_WORKER_ENABLED", "0")
    from app import main
    from app.services import auth, crm_store

    importlib.reload(crm_store)
    importlib.reload(auth)
    monkeypatch.setattr(main, "_STRICT_AUTH", False)
    accounts = [auth.register_user(email=name + "@example.test", password="FlowTestSecret123!",
                                   display_name=name) for name in ("flow-alpha", "flow-beta")]
    assert all(account["success"] for account in accounts)
    client = TestClient(main.create_app())
    yield SimpleNamespace(
        client=client, accounts=accounts, auth=auth, main=main,
        headers=[{"Authorization": "Bearer " + account["access_token"]} for account in accounts],
    )
    client.close()


def graph():
    return {
        "name": "跟进草稿",
        "nodes": [
            {"id": "in", "type": "acquire", "label": "消息入站", "position": {"x": 10, "y": 20},
             "config": {"channel": "chatwoot", "nested": {"preserve": [1, "two"]}}},
            {"id": "reply", "type": "communicate", "label": "草拟回复", "position": {"x": 250, "y": 20},
             "config": {"requires_approval": True}},
        ],
        "edges": [{"id": "edge-one", "source": "in", "target": "reply"}],
    }


def create(product):
    response = product.client.post("/api/kellai/flow/create", json=graph(), headers=product.headers[0])
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_create_update_and_restart_preserve_graph_configuration(product):
    before = datetime.now(timezone.utc)
    first = create(product)
    assert first["status"] == "draft" and first["execution_available"] is False
    assert datetime.fromisoformat(first["created_at"]) >= before
    changed_nodes = list(reversed(first["nodes"]))
    changed_nodes[0]["position"] = {"x": 305, "y": 101}
    updated = product.client.put("/api/kellai/flow/update", headers=product.headers[0], json={
        "id": first["id"], "name": "更新后的草稿", "nodes": changed_nodes, "edges": [],
    })
    assert updated.status_code == 200, updated.text
    from app.api import flow

    importlib.reload(flow)
    replacement = TestClient(product.main.create_app())
    restored = replacement.get("/api/kellai/flow/definitions/" + first["id"], headers=product.headers[0])
    replacement.close()
    assert restored.status_code == 200
    saved = restored.json()["data"]
    assert saved["name"] == "更新后的草稿"
    assert saved["nodes"] == changed_nodes and saved["edges"] == []
    assert saved["created_at"] == first["created_at"]
    assert saved["updated_at"] >= first["updated_at"]


def test_tenant_crud_isolation_and_missing_ids_are_404(product):
    first = create(product)
    client, foreign = product.client, product.headers[1]
    url = "/api/kellai/flow/definitions/" + first["id"]
    assert client.get("/api/kellai/flow/list", headers=foreign).json()["data"] == []
    assert client.get(url, headers=foreign).status_code == 404
    assert client.delete(url, headers=foreign).status_code == 404
    assert client.put("/api/kellai/flow/update", headers=foreign,
                      json={"id": first["id"], "name": "不能覆盖"}).status_code == 404
    assert client.post("/api/kellai/flow/execute", headers=foreign,
                       json={"flow_id": first["id"]}).status_code == 404
    assert client.put("/api/kellai/flow/update", headers=product.headers[0],
                      json={"id": "missing", "name": "不存在"}).status_code == 404
    assert client.delete(url, headers=product.headers[0]).json()["data"]["deleted"]
    assert client.get(url, headers=product.headers[0]).status_code == 404
    assert client.delete(url, headers=product.headers[0]).status_code == 404
    assert create(product)["id"] != first["id"]


def test_drafts_require_login_even_in_development_mode(product):
    assert product.client.get("/api/kellai/flow/list").status_code == 401
    assert product.client.post("/api/kellai/flow/create", json=graph()).status_code == 401
    assert product.client.post("/api/kellai/flow/webhook", json={"url": "https://example.test/hook"}).status_code == 401
    assert product.client.get("/api/kellai/flow/automation-rate").status_code == 401


@pytest.mark.parametrize("role", ["owner", "admin", "sales", "readonly"])
def test_role_permissions_apply_to_draft_changes_and_unavailable_execution(product, role):
    first = create(product)
    with product.auth._conn() as connection:
        connection.execute("UPDATE kellai_users SET role=? WHERE id=?", (role, product.accounts[0]["user"]["id"]))
    headers = product.headers[0]
    assert product.client.get("/api/kellai/flow/list", headers=headers).status_code == 200
    expected_write = 403 if role == "readonly" else 200
    assert product.client.put("/api/kellai/flow/update", headers=headers,
                               json={"id": first["id"], "nodes": []}).status_code == expected_write
    assert product.client.post("/api/kellai/flow/create", headers=headers, json=graph()).status_code == expected_write
    expected_execution = 403 if role == "readonly" else 501
    assert product.client.post("/api/kellai/flow/execute", headers=headers,
                               json={"flow_id": first["id"]}).status_code == expected_execution
    assert product.client.post("/api/kellai/flow/webhook", headers=headers,
                               json={"url": "https://example.test/hook"}).status_code == expected_execution


def test_unimplemented_actions_and_metrics_never_claim_effects(product):
    first = create(product)
    execution = product.client.post("/api/kellai/flow/execute", headers=product.headers[0],
                                     json={"flow_id": first["id"]})
    assert execution.status_code == 501
    assert execution.json()["success"] is False and execution.json()["code"] == 501
    assert "尚未接入" in execution.json()["error"]
    webhook = product.client.post("/api/kellai/flow/webhook", headers=product.headers[0],
                                   json={"url": "https://example.test/hook", "events": ["message.received"]})
    assert webhook.status_code == 501
    assert webhook.json()["success"] is False and webhook.json()["code"] == 501
    assert "未创建或启用" in webhook.json()["error"]
    metric = product.client.get("/api/kellai/flow/automation-rate", headers=product.headers[0]).json()["data"]
    assert metric["rate"] is None and metric["measurement_status"] == "unmeasured"
    assert metric["breakdown"] == []
    templates = product.client.get("/api/kellai/flow/templates").json()["data"]
    assert templates and all(row["is_example"] and row["automation_rate"] is None for row in templates)
    assert all(row["execution_available"] is False for row in templates)


def test_partial_update_supports_clearing_and_rejects_unsupported_authority_fields(product):
    first = create(product)
    cleared = product.client.put("/api/kellai/flow/update", headers=product.headers[0],
                                  json={"id": first["id"], "nodes": [], "edges": []})
    assert cleared.json()["data"]["nodes"] == []
    assert cleared.json()["data"]["edges"] == []
    assert product.client.put("/api/kellai/flow/update", headers=product.headers[0],
                               json={"id": first["id"]}).status_code == 422
    assert product.client.post("/api/kellai/flow/create", headers=product.headers[0],
                                json={**graph(), "team_id": 999}).status_code == 422
