"""v6 流程闭环 API 桩实现。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/kellai/flow", tags=["flow"])

_flows: list[dict[str, Any]] = []


class FlowCreateBody(BaseModel):
    name: str = "新流程"
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class FlowUpdateBody(BaseModel):
    id: str = ""
    name: Optional[str] = None
    nodes: Optional[list] = None
    edges: Optional[list] = None


class ExecuteBody(BaseModel):
    flow_id: str = ""


class WebhookBody(BaseModel):
    url: str = ""
    events: list[str] = Field(default_factory=list)


@router.post("/create")
def create_flow(body: FlowCreateBody) -> dict:
    flow = {"id": f"flow_{len(_flows)}", "name": body.name, "nodes": body.nodes, "edges": body.edges, "created_at": "2026-06-12T00:00:00Z", "updated_at": "2026-06-12T00:00:00Z"}
    _flows.append(flow)
    return {"success": True, "data": flow}


@router.put("/update")
def update_flow(body: FlowUpdateBody) -> dict:
    for f in _flows:
        if f["id"] == body.id:
            if body.name:
                f["name"] = body.name
            return {"success": True, "data": f}
    return {"success": True, "data": None}


@router.get("/list")
def list_flows() -> dict:
    if not _flows:
        _flows.append({"id": "flow_default", "name": "默认流程", "nodes": [], "edges": [], "created_at": "2026-06-12T00:00:00Z", "updated_at": "2026-06-12T00:00:00Z"})
    return {"success": True, "data": _flows}


@router.post("/execute")
def execute(body: ExecuteBody) -> dict:
    return {"success": True, "data": {"id": "exec_1", "flow_id": body.flow_id, "flow_name": "默认流程", "status": "completed", "started_at": "2026-06-12T00:00:00Z", "logs": []}}


@router.get("/anomalies")
def anomalies() -> dict:
    return {"success": True, "data": []}


@router.get("/templates")
def templates() -> dict:
    return {"success": True, "data": [{"id": "tpl_edu", "name": "教育培训", "industry": "education", "description": "获客流程", "nodes": [], "edges": [], "automation_rate": 78}]}


@router.get("/automation-rate")
def automation_rate() -> dict:
    return {"success": True, "data": {"rate": 72, "breakdown": [{"stage": "获客", "rate": 85}]}}


@router.post("/webhook")
def webhook(body: WebhookBody) -> dict:
    return {"success": True, "data": {"id": "wh_1", "url": body.url, "events": body.events, "enabled": True, "created_at": "2026-06-12T00:00:00Z"}}
