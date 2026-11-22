"""The application lifecycle honors disabled background inbox polling."""
import asyncio

import httpx
import pytest

from app.channels import config_store
from app.main import app
from app.services import auth, message_store
from app.services.channel_ingest import sync_inbox
from app.services.tenant_context import tenant_scope


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["0", "1", None], ids=["disabled", "enabled", "default"])
async def test_lifespan_controls_real_inbox_consumption(tool_env, monkeypatch, setting):
    if setting is None:
        monkeypatch.delenv("KELLAI_CHANNEL_WORKER_ENABLED", raising=False)
    else:
        monkeypatch.setenv("KELLAI_CHANNEL_WORKER_ENABLED", setting)
    with tenant_scope(1):
        config_store.create_connection("wechat", {"webhook_token": "fixture-secret"}, connection_id="poll")
        message_store.push_inbox("wechat", connection_id="poll", contact_id="visitor",
                                 direction="inbound", content="durable incoming message", msg_id="incoming")
    headers = {"Authorization": "Bearer " + auth.create_operator_session()["access_token"]}

    # Exercise the actual startup, worker, account adapter, database and shutdown.
    # No mocked run()/create_task() can make the feature pass without consuming
    # (or deliberately preserving) the real queued message.
    async with asyncio.timeout(2):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                        base_url="http://127.0.0.1:8793") as client:
                for _ in range(3):
                    assert (await client.get("/health")).status_code == 200
                response = await client.get("/api/kellai/contacts?connection_id=poll", headers=headers)
                assert response.status_code == 200
                contacts = response.json()["data"]["contacts"]
            with tenant_scope(1):
                queued = message_store.list_inbox(connection_id="poll")
                if setting == "0":
                    assert contacts == []
                    assert [row["id"] for row in queued] == ["incoming"]
                else:
                    assert queued == []
                    assert len(contacts) == 1
                    messages = message_store.get_messages(contacts[0]["customer_id"], connection_id="poll")
                    assert [message.content for message in messages] == ["durable incoming message"]

    if setting == "0":
        # Disabling polling keeps an otherwise valid inbox available for explicit
        # operator sync; it must not disable the app or discard incoming data.
        result = await sync_inbox(team_id=1, connection_id="poll")
        assert result["data"]["synced"] == result["data"]["consumed"] == 1
