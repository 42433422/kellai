"""v7 智能财务 API 桩实现。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/kellai/finance", tags=["finance"])


class AskBody(BaseModel):
    question: str = ""


@router.get("/dashboard")
def dashboard() -> dict:
    return {"success": True, "data": {"revenue": 1280000, "cost": 456000, "profit": 824000, "profit_margin": 64.4, "channel_breakdown": [], "monthly_trend": []}}


@router.post("/ask")
def ask(body: AskBody) -> dict:
    return {"success": True, "data": {"answer": f"关于「{body.question}」：本月营收 ¥1,280,000"}}


@router.get("/budget-suggest")
def budget_suggest() -> dict:
    return {"success": True, "data": {"total_budget": 200000, "allocations": []}}


@router.get("/performance")
def performance() -> dict:
    return {"success": True, "data": [{"user_id": 1, "name": "张伟", "revenue": 285000, "deals": 8, "conversion_rate": 32, "rank": 1}]}


@router.get("/alerts")
def alerts() -> dict:
    return {"success": True, "data": []}


@router.get("/report")
def report(period: str = "2026-06") -> dict:
    return {"success": True, "data": {"id": "rpt_1", "title": f"{period} 报表", "period": period, "generated_at": "2026-06-12T00:00:00Z", "download_url": "#"}}


@router.post("/decision")
def decision() -> dict:
    return {"success": True, "data": {"summary": "建议优化抖音投放", "actions": []}}
