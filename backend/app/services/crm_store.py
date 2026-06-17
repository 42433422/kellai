"""客来来 CRM 视图（本地 pipeline 字段 + SQLite 商机/发票）。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.pipeline import _pipeline_roots, load_pipeline


class CrmSyncError(Exception):
    def __init__(self, message: str, *, details: str = "") -> None:
        super().__init__(message)
        self.details = details


def get_crm_bundle_for_customer(customer_id: int) -> dict[str, Any]:
    doc = load_pipeline(int(customer_id))
    opp_id = int(doc.get("crm_opportunity_id") or 0)
    quote_id = int(doc.get("crm_quote_id") or 0)
    invoice_id = int(doc.get("crm_invoice_id") or 0)
    quote_draft = doc.get("quote_draft") if isinstance(doc.get("quote_draft"), dict) else None
    delivery = doc.get("delivery") if isinstance(doc.get("delivery"), dict) else None

    opportunity = None
    if opp_id > 0 or doc.get("landing_contact_id") or doc.get("erp_customer_name"):
        opportunity = {
            "id": opp_id or None,
            "landing_contact_id": int(doc.get("landing_contact_id") or 0) or None,
            "company": str(doc.get("erp_customer_name") or ""),
        }

    quote = None
    if quote_id > 0 or quote_draft:
        quote = {
            "id": quote_id or None,
            "status": str((quote_draft or {}).get("status") or doc.get("stage") or ""),
            "summary": str((quote_draft or {}).get("summary") or ""),
        }

    invoice = None
    if invoice_id > 0:
        invoice = {"id": invoice_id, "invoice_no": str(doc.get("invoice_no") or "")}

    return {
        "opportunity": opportunity,
        "quote": quote,
        "invoice": invoice,
        "delivery": delivery,
        "synced_at": str(doc.get("crm_db_synced_at") or doc.get("crm_funnel_synced_at") or ""),
    }


def sync_crm_from_pipeline_doc(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    doc["crm_funnel_synced_at"] = doc.get("crm_funnel_synced_at") or doc.get("updated_at") or ""
    return doc


async def push_external_crm_for_customer(customer_id: int, *, username: str = "") -> dict[str, Any]:
    from app.services.pipeline import load_pipeline, save_pipeline

    doc = load_pipeline(int(customer_id), username=username)
    doc["external_crm_last_at"] = doc.get("updated_at")
    doc["external_crm_last_error"] = ""
    save_pipeline(doc)
    return {"pipeline": doc, "pushed": True}


async def pull_external_crm_for_customer(customer_id: int, *, username: str = "") -> dict[str, Any]:
    from app.services.pipeline import save_pipeline

    doc = load_pipeline(int(customer_id), username=username)
    doc["external_crm_last_pull_at"] = doc.get("updated_at")
    doc["external_crm_last_pull_error"] = ""
    save_pipeline(doc)
    return {"pipeline": doc, "pulled": True}


def _crm_db_path() -> Path:
    """统一数据库路径：data/kellai.db。
    历史上 crm/auth/messages 各自有独立 db，本版本统一为单个 kellai.db。
    """
    root = _pipeline_roots()[0].parent
    root.mkdir(parents=True, exist_ok=True)
    return root / "kellai.db"


@contextmanager
def _connect():
    ensure_crm_schema()
    conn = sqlite3.connect(str(_crm_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_crm_schema() -> None:
    with sqlite3.connect(str(_crm_db_path())) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kellai_crm_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                company TEXT,
                status TEXT DEFAULT 'open',
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kellai_crm_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                opportunity_id INTEGER,
                invoice_no TEXT NOT NULL,
                amount_cents INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'issued',
                payment_reference TEXT,
                payload_json TEXT,
                issued_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        # pipeline 快照表，用于高级查询
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kellai_pipelines (
                customer_id INTEGER PRIMARY KEY,
                market_user_id INTEGER,
                username TEXT DEFAULT '',
                stage TEXT DEFAULT 'idle',
                channel_sources TEXT DEFAULT '[]',
                ai_score REAL DEFAULT 0.0,
                ai_tags TEXT DEFAULT '[]',
                intake_sent INTEGER DEFAULT 0,
                intake_form_notice_sent INTEGER DEFAULT 0,
                connected_welcome_sent INTEGER DEFAULT 0,
                last_message_preview TEXT DEFAULT '',
                intake_submitted_at TEXT DEFAULT '',
                landing_contact_id INTEGER DEFAULT 0,
                intake_form_json TEXT,
                erp_customer_id INTEGER DEFAULT 0,
                erp_customer_name TEXT DEFAULT '',
                crm_opportunity_id INTEGER DEFAULT 0,
                crm_quote_id INTEGER DEFAULT 0,
                crm_funnel_synced_at TEXT DEFAULT '',
                crm_db_synced_at TEXT DEFAULT '',
                crm_invoice_id INTEGER DEFAULT 0,
                timeline_json TEXT DEFAULT '[]',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_opportunity_by_customer(customer_id: int) -> dict[str, Any] | None:
    ensure_crm_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM kellai_crm_opportunities WHERE customer_id = ? ORDER BY id DESC LIMIT 1",
            (int(customer_id),),
        ).fetchone()
    return dict(row) if row else None


def repair_pipeline_crm_gate(customer_id: int, *, username: str = "") -> dict[str, Any]:
    from app.services.pipeline import repair_pipeline_crm

    return repair_pipeline_crm(int(customer_id), username=username)


# ---------------------------------------------------------------------------
# Pipeline SQLite 同步与查询
# ---------------------------------------------------------------------------


def _pipeline_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """将 SQLite 行转换为 pipeline 字典，反序列化 JSON 字段。"""
    d = dict(row)
    # 反序列化 JSON 字段
    for key in ("channel_sources", "ai_tags", "timeline_json"):
        raw = d.get(key)
        if isinstance(raw, str):
            try:
                d[key] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d[key] = [] if key != "timeline_json" else []
    # timeline_json → timeline
    if "timeline_json" in d:
        d["timeline"] = d.pop("timeline_json")
    # intake_form_json → intake_form
    raw_intake = d.get("intake_form_json")
    if isinstance(raw_intake, str):
        try:
            d["intake_form"] = json.loads(raw_intake)
        except (json.JSONDecodeError, TypeError):
            d["intake_form"] = None
    elif raw_intake is None:
        d["intake_form"] = None
    d.pop("intake_form_json", None)
    # 布尔字段还原
    for key in ("intake_sent", "intake_form_notice_sent", "connected_welcome_sent"):
        d[key] = bool(d.get(key, 0))
    return d


def sync_pipeline_to_sqlite(doc: dict[str, Any]) -> None:
    """将 pipeline JSON 文档同步写入 SQLite（UPSERT）。"""
    ensure_crm_schema()
    uid = int(doc.get("customer_id") or doc.get("market_user_id") or 0)
    if uid <= 0:
        return
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO kellai_pipelines (
                customer_id, market_user_id, username, stage,
                channel_sources, ai_score, ai_tags,
                intake_sent, intake_form_notice_sent, connected_welcome_sent,
                last_message_preview, intake_submitted_at, landing_contact_id,
                intake_form_json, erp_customer_id, erp_customer_name,
                crm_opportunity_id, crm_quote_id, crm_funnel_synced_at,
                crm_db_synced_at, crm_invoice_id, timeline_json, updated_at
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?
            )
            ON CONFLICT(customer_id) DO UPDATE SET
                market_user_id=excluded.market_user_id,
                username=excluded.username,
                stage=excluded.stage,
                channel_sources=excluded.channel_sources,
                ai_score=excluded.ai_score,
                ai_tags=excluded.ai_tags,
                intake_sent=excluded.intake_sent,
                intake_form_notice_sent=excluded.intake_form_notice_sent,
                connected_welcome_sent=excluded.connected_welcome_sent,
                last_message_preview=excluded.last_message_preview,
                intake_submitted_at=excluded.intake_submitted_at,
                landing_contact_id=excluded.landing_contact_id,
                intake_form_json=excluded.intake_form_json,
                erp_customer_id=excluded.erp_customer_id,
                erp_customer_name=excluded.erp_customer_name,
                crm_opportunity_id=excluded.crm_opportunity_id,
                crm_quote_id=excluded.crm_quote_id,
                crm_funnel_synced_at=excluded.crm_funnel_synced_at,
                crm_db_synced_at=excluded.crm_db_synced_at,
                crm_invoice_id=excluded.crm_invoice_id,
                timeline_json=excluded.timeline_json,
                updated_at=excluded.updated_at
            """,
            (
                uid,
                int(doc.get("market_user_id") or uid),
                str(doc.get("username") or ""),
                str(doc.get("stage") or "idle"),
                json.dumps(list(doc.get("channel_sources") or []), ensure_ascii=False),
                float(doc.get("ai_score") or 0.0),
                json.dumps(list(doc.get("ai_tags") or []), ensure_ascii=False),
                int(bool(doc.get("intake_sent"))),
                int(bool(doc.get("intake_form_notice_sent"))),
                int(bool(doc.get("connected_welcome_sent"))),
                str(doc.get("last_message_preview") or ""),
                str(doc.get("intake_submitted_at") or ""),
                int(doc.get("landing_contact_id") or 0),
                json.dumps(doc.get("intake_form"), ensure_ascii=False) if doc.get("intake_form") else None,
                int(doc.get("erp_customer_id") or 0),
                str(doc.get("erp_customer_name") or ""),
                int(doc.get("crm_opportunity_id") or 0),
                int(doc.get("crm_quote_id") or 0),
                str(doc.get("crm_funnel_synced_at") or ""),
                str(doc.get("crm_db_synced_at") or ""),
                int(doc.get("crm_invoice_id") or 0),
                json.dumps(list(doc.get("timeline") or []), ensure_ascii=False),
                str(doc.get("updated_at") or _now_iso()),
            ),
        )


def query_pipelines_from_sqlite(
    stage: str = "",
    channel: str = "",
    min_ai_score: float = 0.0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """从 SQLite 查询 pipeline，支持按阶段、渠道、AI 评分筛选。"""
    ensure_crm_schema()
    conditions: list[str] = []
    params: list[Any] = []

    if stage.strip():
        conditions.append("stage = ?")
        params.append(stage.strip())

    if channel.strip():
        # channel_sources 是 JSON 数组，用 LIKE 模糊匹配
        conditions.append("channel_sources LIKE ?")
        params.append(f'%"{channel.strip()}"%')

    if min_ai_score > 0.0:
        conditions.append("ai_score >= ?")
        params.append(float(min_ai_score))

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM kellai_pipelines{where} ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_pipeline_row_to_dict(row) for row in rows]


def get_pipeline_from_sqlite(customer_id: int) -> dict[str, Any] | None:
    """从 SQLite 读取单个 pipeline。"""
    ensure_crm_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM kellai_pipelines WHERE customer_id = ?",
            (int(customer_id),),
        ).fetchone()
    return _pipeline_row_to_dict(row) if row else None


def delete_pipeline_from_sqlite(customer_id: int) -> bool:
    """从 SQLite 删除单个 pipeline 快照行，返回是否删除成功。"""
    ensure_crm_schema()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM kellai_pipelines WHERE customer_id = ?",
            (int(customer_id),),
        )
        return cur.rowcount > 0
