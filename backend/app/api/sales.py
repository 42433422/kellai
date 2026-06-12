"""v3 销售增长 API 桩实现。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/kellai/sales", tags=["sales"])

_flow_state: dict[int, dict[str, Any]] = {}
_quotes: dict[int, dict[str, Any]] = {}


class AutoFlowBody(BaseModel):
    customer_id: int = Field(default=1001, gt=0)
    step: Optional[str] = None


class QuoteBody(BaseModel):
    customer_id: int = Field(default=1001, gt=0)


class ContractBody(BaseModel):
    customer_id: int = Field(default=1001, gt=0)
    quote_id: Optional[str] = None


STEPS = ["requirement", "proposal", "promotion", "signing"]
STEP_LABELS = {
    "requirement": "需求确认",
    "proposal": "方案推荐",
    "promotion": "促单",
    "signing": "签约",
}


def _get_flow(customer_id: int) -> dict[str, Any]:
    if customer_id not in _flow_state:
        _flow_state[customer_id] = {
            "id": f"flow_{customer_id}",
            "customer_id": customer_id,
            "customer_name": f"客户{customer_id}",
            "current_step": "requirement",
            "status": "idle",
            "started_at": "2026-06-12T00:00:00Z",
            "updated_at": "2026-06-12T00:00:00Z",
            "steps_completed": [],
        }
    return _flow_state[customer_id]


@router.post("/auto-flow")
def auto_flow(body: AutoFlowBody) -> dict[str, Any]:
    flow = _get_flow(body.customer_id)
    flow["status"] = "running"
    if body.step:
        flow["current_step"] = body.step
    else:
        idx = STEPS.index(flow["current_step"])
        if flow["current_step"] not in flow["steps_completed"]:
            flow["steps_completed"].append(flow["current_step"])
        if idx < len(STEPS) - 1:
            flow["current_step"] = STEPS[idx + 1]
        else:
            flow["status"] = "completed"
    return {"success": True, "data": flow}


@router.post("/quote")
def quote(body: QuoteBody) -> dict[str, Any]:
    total = 58000
    q = {
        "id": f"quote_{body.customer_id}",
        "customer_id": body.customer_id,
        "items": [
            {"name": "标准版 CRM", "quantity": 10, "unit_price": 5000, "total": 50000},
            {"name": "AI 模块", "quantity": 1, "unit_price": 8000, "total": 8000},
        ],
        "subtotal": 58000,
        "discount": 0.05,
        "total": total,
        "valid_until": "2026-07-12",
        "created_at": "2026-06-12T00:00:00Z",
    }
    _quotes[body.customer_id] = q
    return {"success": True, "data": q}


@router.get("/funnel-trace")
def funnel_trace(customer_id: Optional[int] = None) -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "customer_id": customer_id,
            "nodes": [
                {"stage": "no_contact", "stage_label": "未接触", "timestamp": "2026-06-01T00:00:00Z"},
                {"stage": "connected", "stage_label": "已建联", "timestamp": "2026-06-03T00:00:00Z"},
                {"stage": "quoted", "stage_label": "已报价", "timestamp": "2026-06-08T00:00:00Z"},
                {"stage": "signed", "stage_label": "已签", "timestamp": "2026-06-11T00:00:00Z"},
            ],
            "edges": [
                {"from_stage": "no_contact", "to_stage": "connected", "conversion_rate": 72},
                {"from_stage": "connected", "to_stage": "quoted", "conversion_rate": 58},
                {"from_stage": "quoted", "to_stage": "signed", "conversion_rate": 35},
            ],
            "overall_conversion": 22,
        },
    }


@router.post("/contract")
def contract(body: ContractBody) -> dict[str, Any]:
    q = _quotes.get(body.customer_id, {"total": 58000, "id": "quote_default"})
    return {
        "success": True,
        "data": {
            "id": f"contract_{body.customer_id}",
            "customer_id": body.customer_id,
            "quote_id": body.quote_id or q["id"],
            "status": "pending_sign",
            "title": "客来来 CRM 服务合同",
            "content_preview": f"合同金额 ¥{q['total']}",
            "sign_url": f"https://sign.kellai.com/{body.customer_id}",
            "created_at": "2026-06-12T00:00:00Z",
        },
    }


@router.get("/ltv/{customer_id}")
def ltv(customer_id: int) -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "customer_id": customer_id,
            "predicted_ltv": 85000,
            "confidence": 0.82,
            "factors": [{"name": "行业系数", "impact": 1.2}, {"name": "AI 评分", "impact": 1.1}],
            "recommendation": "高价值客户，建议优先跟进",
        },
    }


@router.get("/performance")
def performance(period: str = "month") -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "period": period,
            "revenue_target": 500000,
            "revenue_actual": 342000,
            "completion_rate": 68.4,
            "deals_closed": 12,
            "avg_deal_size": 28500,
            "goals": [],
        },
    }


@router.get("/attribution")
def attribution() -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "date_range": "2026-06-01 ~ 2026-06-12",
            "total_revenue": 342000,
            "channels": [
                {"channel": "wechat", "channel_label": "微信", "leads": 45, "conversions": 5, "revenue": 119700, "contribution_pct": 35},
                {"channel": "douyin", "channel_label": "抖音", "leads": 38, "conversions": 3, "revenue": 85500, "contribution_pct": 25},
            ],
        },
    }


@router.get("/script-hint")
def script_hint(customer_id: int = 1001, stage: str = "quoted") -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "customer_id": customer_id,
            "stage": stage,
            "stage_label": STEP_LABELS.get(stage, stage),
            "suggestion": "当前处于关键销售节点",
            "scripts": ["您好，关于报价方案我们可以进一步沟通", "本周签约可享专属优惠"],
        },
    }
