"""Tenant-owned workflow drafts; graph execution is not integrated yet.

Automatic replies use the existing delivery runtime. These diagrams do not
register webhooks or execute actions through a second workflow engine.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.crm_store import _crm_db_path
from app.services.messaging import request_actor

router = APIRouter(prefix="/api/kellai/flow", tags=["flow"])


class FlowCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="新流程", min_length=1, max_length=200)
    nodes: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    edges: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class FlowUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    nodes: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    edges: list[dict[str, Any]] | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def nonempty_update(self):
        if self.name is None and self.nodes is None and self.edges is None:
            raise ValueError("请提供需要更新的流程名称、节点或连线")
        return self


class ExecuteBody(BaseModel):
    flow_id: str = Field(min_length=1, max_length=100)


class WebhookBody(BaseModel):
    url: str = ""
    events: list[str] = Field(default_factory=list)


@contextmanager
def _connect():
    connection = sqlite3.connect(str(_crm_db_path()), timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS kellai_flow_drafts (
                team_id INTEGER NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                nodes_json TEXT NOT NULL,
                edges_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (team_id, id)
            )"""
        )
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _document(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "name": row["name"],
        "nodes": json.loads(row["nodes_json"]), "edges": json.loads(row["edges_json"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "status": "draft", "execution_available": False,
    }


def _get(connection: sqlite3.Connection, team_id: int, flow_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM kellai_flow_drafts WHERE team_id=? AND id=?", (team_id, flow_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="当前团队不存在此流程草稿")
    return row


@router.post("/create")
def create_flow(body: FlowCreateBody, request: Request) -> dict:
    team_id = int(request_actor(request)["team_id"])
    flow_id = "flow_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO kellai_flow_drafts "
            "(team_id, id, name, nodes_json, edges_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (team_id, flow_id, body.name, json.dumps(body.nodes, ensure_ascii=False),
             json.dumps(body.edges, ensure_ascii=False), now, now),
        )
        document = _document(_get(connection, team_id, flow_id))
    return {"success": True, "data": document}


@router.put("/update")
def update_flow(body: FlowUpdateBody, request: Request) -> dict:
    team_id = int(request_actor(request)["team_id"])
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        document = _document(_get(connection, team_id, body.id))
        document.update(body.model_dump(exclude_none=True, exclude={"id"}))
        connection.execute(
            "UPDATE kellai_flow_drafts SET name=?, nodes_json=?, edges_json=?, updated_at=? "
            "WHERE team_id=? AND id=?",
            (document["name"], json.dumps(document["nodes"], ensure_ascii=False),
             json.dumps(document["edges"], ensure_ascii=False), datetime.now(timezone.utc).isoformat(),
             team_id, body.id),
        )
        document = _document(_get(connection, team_id, body.id))
    return {"success": True, "data": document}


@router.get("/list")
def list_flows(request: Request) -> dict:
    team_id = int(request_actor(request, read=True)["team_id"])
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM kellai_flow_drafts WHERE team_id=? ORDER BY updated_at DESC, id", (team_id,),
        ).fetchall()
    return {"success": True, "data": [_document(row) for row in rows]}


@router.get("/definitions/{flow_id}")
def get_flow(flow_id: str, request: Request) -> dict:
    team_id = int(request_actor(request, read=True)["team_id"])
    with _connect() as connection:
        document = _document(_get(connection, team_id, flow_id))
    return {"success": True, "data": document}


@router.delete("/definitions/{flow_id}")
def delete_flow(flow_id: str, request: Request) -> dict:
    team_id = int(request_actor(request)["team_id"])
    with _connect() as connection:
        deleted = connection.execute(
            "DELETE FROM kellai_flow_drafts WHERE team_id=? AND id=?", (team_id, flow_id),
        ).rowcount
        if not deleted:
            raise HTTPException(status_code=404, detail="当前团队不存在此流程草稿")
    return {"success": True, "data": {"id": flow_id, "deleted": True}}


@router.post("/execute")
def execute(body: ExecuteBody, request: Request) -> dict:
    team_id = int(request_actor(request)["team_id"])
    with _connect() as connection:
        _get(connection, team_id, body.flow_id)
    raise HTTPException(status_code=501, detail={
        "code": "flow_execution_not_integrated", "message": "流程执行尚未接入审批与任务运行时，当前仅支持保存草稿",
    })


@router.get("/anomalies")
def anomalies(request: Request) -> dict:
    request_actor(request, read=True)
    return {"success": True, "data": [], "measurement_status": "unmeasured",
            "reason": "flow_execution_not_integrated"}


@router.get("/templates")
def templates() -> dict:
    return {"success": True, "data": [{
        "id": "tpl_edu", "name": "教育培训流程示例", "industry": "education",
        "description": "用于编辑草稿的获客、沟通与售后结构示例，执行尚未接入。",
        "nodes": [
            {"id": "lead", "type": "acquire", "label": "接入线索", "config": {}, "position": {"x": 0, "y": 0}},
            {"id": "reply", "type": "communicate", "label": "需求沟通", "config": {}, "position": {"x": 240, "y": 0}},
            {"id": "followup", "type": "after_sales", "label": "后续服务", "config": {}, "position": {"x": 240, "y": 160}},
        ],
        "edges": [{"id": "lead-reply", "source": "lead", "target": "reply"},
                  {"id": "reply-followup", "source": "reply", "target": "followup"}],
        "automation_rate": None, "is_example": True, "execution_available": False,
    }]}


@router.get("/automation-rate")
def automation_rate(request: Request) -> dict:
    request_actor(request, read=True)
    return {"success": True, "data": {"rate": None, "breakdown": [], "measurement_status": "unmeasured",
                                      "reason": "flow_execution_not_integrated"}}


@router.post("/webhook")
def webhook(body: WebhookBody, request: Request) -> dict:
    request_actor(request)
    raise HTTPException(status_code=501, detail={
        "code": "flow_webhook_not_integrated", "message": "流程 Webhook 尚未接入执行运行时，未创建或启用订阅",
    })
