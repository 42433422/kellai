"""Legacy messages and send ledger survive the account-isolation migration."""
import hashlib
import json
import sqlite3

import pytest

from app.channels import config_store
from app.channels.base import UnifiedMessage
from app.services import auth, message_store, outbound_delivery
from app.services.tenant_context import tenant_scope


@pytest.mark.asyncio
async def test_legacy_tables_keep_sent_unknown_consumed_and_exact_owner_bindings(tool_env):
    db_path = tool_env / "kellai.db"
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE kellai_messages (team_id INTEGER NOT NULL,id TEXT NOT NULL,customer_id INTEGER NOT NULL,
                channel_type TEXT NOT NULL,contact_id TEXT NOT NULL,contact_name TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL,content TEXT NOT NULL DEFAULT '',content_type TEXT NOT NULL DEFAULT 'text',
                metadata_json TEXT,created_at TEXT NOT NULL,is_read INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(team_id,id));
            CREATE TABLE kellai_channel_inbox (team_id INTEGER NOT NULL,id TEXT NOT NULL,channel_type TEXT NOT NULL,
                contact_id TEXT NOT NULL,contact_name TEXT NOT NULL DEFAULT '',direction TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',content_type TEXT NOT NULL DEFAULT 'text',metadata_json TEXT,
                received_at TEXT NOT NULL,consumed INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(team_id,id));
            CREATE TABLE kellai_outbound_deliveries (team_id INTEGER NOT NULL,request_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,payload_json TEXT NOT NULL,channel_type TEXT NOT NULL,message_id TEXT NOT NULL,
                status TEXT NOT NULL,delivery_token TEXT NOT NULL,lease_until TEXT NOT NULL,result_json TEXT NOT NULL DEFAULT '{}',
                provider_message_id TEXT NOT NULL DEFAULT '',provider_state TEXT NOT NULL DEFAULT '',projected INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(team_id,request_id));
            CREATE TABLE kellai_customers (id INTEGER PRIMARY KEY, private_history TEXT);
            INSERT INTO kellai_customers VALUES(42,'retained business archive');
        """)
        for team, mid, kind, direction in ((1,"sent-local","telegram","outbound"),(1,"unassigned","wechat","inbound"),(2,"other-owner","telegram","inbound")):
            db.execute("INSERT INTO kellai_messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (team,mid,42,kind,"same-address","Historical name",direction,"history","text",json.dumps({"team_id":team}),"2025-01-01",1))
        db.execute("INSERT INTO kellai_channel_inbox VALUES(?,?,?,?,?,?,?,?,?,?,?)",(1,"inbox-id","telegram","same-address","name","inbound","old","text","{}","2025-01-01",1))
        for status, request in (("accepted","old-sent"),("unknown","old-unknown")):
            payload={"customer_id":42,"channel_type":"telegram","contact_id":"same-address","contact_name":"Historical name",
                     "direction":"outbound","content":"history","content_type":"text","metadata":{"team_id":1}}
            db.execute("INSERT INTO kellai_outbound_deliveries VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(1,request,"legacy-fingerprint",
                json.dumps(payload),"telegram","sent-local",status,"lease-secret","2025-01-01",'{"success":true}',"provider-id",status,1,"2025-01-01","2025-01-01"))
    legacy = tool_env / "tenants/1/channel_configs.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"telegram":{"enabled":True,"config":{"bot_token":"old-secret"}}}))
    with tenant_scope(1):
        message_store.ensure_messages_schema()
        outbound_delivery.ensure_schema()
        assert message_store.migrate_account_bindings() == 2
        assert message_store.migrate_account_bindings() == 0
        receipt = outbound_delivery.get_delivery("old-sent")
        assert receipt["connection_id"] == "legacy-telegram" and receipt["status"] == "accepted" and receipt["persisted"]
        unknown = outbound_delivery.get_delivery("old-unknown")
        assert unknown["status"] == "unknown" and not unknown["dispatch_allowed"]
        with pytest.raises(outbound_delivery.DeliveryConflict):
            outbound_delivery.prepare_external(UnifiedMessage(id="",connection_id="legacy-telegram",customer_id=42,
                channel_type="telegram",contact_id="same-address",contact_name="Historical name",direction="outbound",content="history",created_at="now"),
                idempotency_key="old-sent",team_id=1)
        assert message_store.list_inbox(connection_id="legacy-telegram") == []
        config_store.create_connection("wechat", {"official_app_id":"new","official_app_secret":"new"},connection_id="new-account")
        message_store.migrate_account_bindings()
        assert message_store.get_messages(42,connection_id="new-account") == []
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT count(*) FROM kellai_messages").fetchone()[0] == 3
        assert db.execute("SELECT connection_id FROM kellai_messages WHERE id='unassigned'").fetchone()[0] == ""
        assert db.execute("SELECT connection_id FROM kellai_messages WHERE id='other-owner'").fetchone()[0] == ""
        assert db.execute("SELECT private_history FROM kellai_customers").fetchone()[0] == "retained business archive"
        assert db.execute("SELECT count(*) FROM kellai_outbound_deliveries").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_pre_tenant_schema_uses_each_rows_verified_owner_and_preserves_unattributed(tool_env, monkeypatch):
    monkeypatch.delenv("KELLAI_WORKSPACE_ID")
    with sqlite3.connect(tool_env / "kellai.db") as db:
        db.execute("""CREATE TABLE kellai_messages (id TEXT PRIMARY KEY,customer_id INTEGER,channel_type TEXT,
            contact_id TEXT,contact_name TEXT,direction TEXT,content TEXT,metadata_json TEXT,created_at TEXT)""")
        for mid, metadata in (("one",'{"team_id":1}'),("two",'{"team_id":2}'),("unattributed",'{}')):
            db.execute("INSERT INTO kellai_messages VALUES(?,?,?,?,?,?,?,?,?)", (mid,9,"telegram","id","name","inbound","keep",metadata,"2024-01-01"))
    with pytest.raises(RuntimeError, match="多个工作区"):
        auth.workspace_id()
    message_store.ensure_messages_schema()
    with sqlite3.connect(tool_env / "kellai.db") as db:
        assert dict(db.execute("SELECT id,team_id FROM kellai_messages")) == {"one":1,"two":2,"unattributed":0}
        assert db.execute("SELECT count(*) FROM kellai_messages").fetchone()[0] == 3
