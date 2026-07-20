from __future__ import annotations

import sqlite3
import importlib
from datetime import datetime, timezone

import pytest

from app.channels.base import UnifiedMessage
from app.channels import config_store
from app.services import auto_reply_runtime, llm_config, message_store, workforce_routing
from app.services.crm_store import _crm_db_path
from app.services.pipeline import create_customer, list_pipeline_client_summaries
from app.services.tenant_context import TenantIsolationError, tenant_scope


def _message(team_id: int, customer_id: int, content: str) -> UnifiedMessage:
    return UnifiedMessage(
        id="shared-message-id",
        customer_id=customer_id,
        channel_type="douyin",
        contact_id="shared-contact",
        contact_name=f"租户{team_id}客户",
        direction="inbound",
        content=content,
        content_type="text",
        metadata={"team_id": team_id},
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def test_customer_message_inbox_and_config_are_tenant_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("KELLAI_CHANNEL_CONFIG_PATH", raising=False)

    with tenant_scope(101):
        customer_a = create_customer({"name": "A 租户客户"})
        customer_id = int(customer_a["customer_id"])
        message_store.save_message(_message(101, customer_id, "A 租户消息"))
        message_store.push_inbox(
            "douyin",
            contact_id="shared-contact",
            direction="inbound",
            content="A 租户收件箱",
            metadata={"team_id": 101},
            msg_id="shared-inbox-id",
        )
        config_store.save("douyin", {"client_key": "tenant-a"})
        llm_config.save_config({"provider": "deepseek", "model": "model-a"})

    with tenant_scope(202):
        customer_b = create_customer({"name": "B 租户客户"})
        assert int(customer_b["customer_id"]) == customer_id
        message_store.save_message(_message(202, customer_id, "B 租户消息"))
        message_store.push_inbox(
            "douyin",
            contact_id="shared-contact",
            direction="inbound",
            content="B 租户收件箱",
            metadata={"team_id": 202},
            msg_id="shared-inbox-id",
        )
        config_store.save("douyin", {"client_key": "tenant-b"})
        llm_config.save_config({"provider": "deepseek", "model": "model-b"})

    with tenant_scope(101):
        assert [row["display_name"] for row in list_pipeline_client_summaries()] == [
            "A 租户客户"
        ]
        assert [row.content for row in message_store.get_messages(customer_id)] == [
            "A 租户消息"
        ]
        assert [row["content"] for row in message_store.list_inbox("douyin")] == [
            "A 租户收件箱"
        ]
        assert config_store.get_field("douyin", "client_key") == "tenant-a"
        assert llm_config.public_config()["model"] == "model-a"
        with pytest.raises(TenantIsolationError):
            message_store.get_messages(customer_id, team_id=202)

    with tenant_scope(202):
        assert [row["display_name"] for row in list_pipeline_client_summaries()] == [
            "B 租户客户"
        ]
        assert [row.content for row in message_store.get_messages(customer_id)] == [
            "B 租户消息"
        ]
        assert [row["content"] for row in message_store.list_inbox("douyin")] == [
            "B 租户收件箱"
        ]
        assert config_store.get_field("douyin", "client_key") == "tenant-b"
        assert llm_config.public_config()["model"] == "model-b"


def test_auto_reply_and_assignment_keys_include_tenant(monkeypatch, tmp_path):
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        auto_reply_runtime,
        "_enabled_config",
        lambda: {
            "autoReplyEnabled": True,
            "autoReplyStages": [],
            "confirmScenarios": [],
        },
    )

    with sqlite3.connect(str(_crm_db_path())) as conn:
        conn.execute(
            """
            CREATE TABLE kellai_users (
                id INTEGER PRIMARY KEY,
                team_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.executemany(
            "INSERT INTO kellai_users(id, team_id, display_name, role) VALUES (?, ?, ?, 'sales')",
            [(1001, 101, "A 客服"), (2001, 202, "B 客服")],
        )

    for team_id, assignee_id in ((101, 1001), (202, 2001)):
        with tenant_scope(team_id):
            create_customer({"name": f"租户{team_id}客户"})
            assert auto_reply_runtime.enqueue_message(
                _message(team_id, 90001, f"租户{team_id}入站")
            )
            assignment = workforce_routing.assign_customer(
                customer_id=90001,
                team_id=team_id,
                assignee_user_id=assignee_id,
                actor_user_id=assignee_id,
            )
            assert assignment["team_id"] == team_id

    with sqlite3.connect(str(_crm_db_path())) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM kellai_auto_reply_jobs "
            "WHERE inbound_message_id='shared-message-id'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM kellai_customer_assignments WHERE customer_id=90001"
        ).fetchone()[0] == 2

    with tenant_scope(101):
        assignment = workforce_routing.assignment_for_customer(90001)
        assert assignment and assignment["assignee_user_id"] == 1001
        assert auto_reply_runtime.complete_job(
            "shared-message-id", success=True, team_id=202
        ) is False
        assert auto_reply_runtime.runtime_status(team_id=101)["counts"] == {
            "pending": 1
        }


def test_http_tenant_identity_comes_from_authenticated_token(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app import main
    from app.services import auth, crm_store

    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "_STRICT_AUTH", True)
    importlib.reload(crm_store)
    importlib.reload(auth)

    tenant_a = auth.register_user(
        email="tenant-a@example.com",
        password="TenantA123",
        display_name="Tenant A",
    )
    tenant_b = auth.register_user(
        email="tenant-b@example.com",
        password="TenantB123",
        display_name="Tenant B",
    )
    assert tenant_a["success"] and tenant_b["success"]

    client = TestClient(main.create_app())
    headers_a = {"Authorization": f"Bearer {tenant_a['access_token']}"}
    headers_b = {"Authorization": f"Bearer {tenant_b['access_token']}"}
    created_a = client.post(
        "/api/kellai/customers", json={"name": "A 租户 HTTP 客户"}, headers=headers_a
    )
    created_b = client.post(
        "/api/kellai/customers", json={"name": "B 租户 HTTP 客户"}, headers=headers_b
    )
    assert created_a.status_code == 200
    assert created_b.status_code == 200
    assert created_a.json()["data"]["customer_id"] == created_b.json()["data"]["customer_id"]

    rows_a = client.get("/api/kellai/customers", headers=headers_a).json()["data"][
        "customers"
    ]
    rows_b = client.get("/api/kellai/customers", headers=headers_b).json()["data"][
        "customers"
    ]
    assert [row["display_name"] for row in rows_a] == ["A 租户 HTTP 客户"]
    assert [row["display_name"] for row in rows_b] == ["B 租户 HTTP 客户"]
    assert client.get("/api/kellai/customers").status_code == 401
