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
STEP_META = {
    "requirement": {
        "probability": 25,
        "ai_insight": "客户处于需求澄清期，AI 已识别预算区间与决策链，核心关注获客效率与实施周期。",
        "next_action": "与对接人确认预算与决策流程，预约需求调研会",
        "checklist": ["确认预算区间", "梳理决策链 / 关键决策人", "明确期望上线时间", "记录核心痛点"],
    },
    "proposal": {
        "probability": 52,
        "ai_insight": "基于客户画像推荐标准版 + AI 助手组合，建议突出 ROI 与同行业标杆案例。",
        "next_action": "发送定制方案与报价，预约方案讲解会",
        "checklist": ["输出定制方案", "附标杆案例", "生成智能报价", "邀请决策人参会"],
    },
    "promotion": {
        "probability": 74,
        "ai_insight": "客户已多次查看报价，处于决策窗口期，建议用限时优惠制造紧迫感推动签约。",
        "next_action": "推送限时优惠并锁定签约时间",
        "checklist": ["确认最终折扣审批", "推送限时优惠", "解决付款异议", "锁定签约时间窗"],
    },
    "signing": {
        "probability": 90,
        "ai_insight": "进入签约阶段，合同条款已对齐，建议引导电子签约缩短回款周期。",
        "next_action": "生成电子合同并引导线上签署",
        "checklist": ["生成电子合同", "法务条款确认", "客户完成电子签", "排期实施与培训"],
    },
}
OWNERS = ["张敏", "李航", "王磊", "陈悦", "刘洋"]


def _sync_meta(flow: dict[str, Any]) -> None:
    meta = STEP_META[flow["current_step"]]
    if flow["status"] == "completed":
        flow["win_probability"] = 100
        flow["next_action"] = "已签约成交，转入交付与客户成功流程"
    else:
        flow["win_probability"] = meta["probability"]
        flow["next_action"] = meta["next_action"]
    flow["ai_insight"] = meta["ai_insight"]
    flow["checklist"] = meta["checklist"]


def _get_flow(customer_id: int) -> dict[str, Any]:
    if customer_id not in _flow_state:
        flow = {
            "id": f"flow_{customer_id}",
            "customer_id": customer_id,
            "customer_name": f"客户{customer_id}",
            "current_step": "requirement",
            "status": "idle",
            "started_at": "2026-06-12T00:00:00Z",
            "updated_at": "2026-06-12T00:00:00Z",
            "steps_completed": [],
            "deal_value": 120000 + (customer_id % 9) * 20000,
            "expected_close_date": "2026-07-03",
            "owner": OWNERS[customer_id % len(OWNERS)],
            "timeline": [
                {"step": "requirement", "label": "需求确认", "at": "2026-06-12T00:00:00Z", "note": "流程启动，进入需求确认阶段"}
            ],
        }
        _sync_meta(flow)
        _flow_state[customer_id] = flow
    return _flow_state[customer_id]


@router.get("/flow")
def get_flow(customer_id: int = 1001) -> dict[str, Any]:
    return {"success": True, "data": _get_flow(customer_id)}


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
            nxt = STEPS[idx + 1]
            flow["current_step"] = nxt
            flow.setdefault("timeline", []).append(
                {"step": nxt, "label": STEP_LABELS[nxt], "at": "2026-06-13T00:00:00Z", "note": f"AI 推进至「{STEP_LABELS[nxt]}」阶段"}
            )
        else:
            flow["status"] = "completed"
            flow.setdefault("timeline", []).append(
                {"step": "signing", "label": "已成交", "at": "2026-06-13T00:00:00Z", "note": "客户完成签约，商机赢单"}
            )
    _sync_meta(flow)
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


_PERIOD_PROFILE = {
    "week": {"target": 125000, "actual": 96000, "deals": 4, "momentum": 8.1, "label": "本周"},
    "month": {"target": 500000, "actual": 342000, "deals": 12, "momentum": 5.2, "label": "本月"},
    "quarter": {"target": 1500000, "actual": 1124000, "deals": 38, "momentum": 11.6, "label": "本季度"},
    "year": {"target": 6000000, "actual": 4380000, "deals": 152, "momentum": 18.4, "label": "本年"},
}


def _build_reps(scale: int) -> list[dict[str, Any]]:
    raw = [
        ("张敏", 0.31, 0.28, 42),
        ("李航", 0.26, 0.24, 38),
        ("王磊", 0.20, 0.22, 35),
        ("陈悦", 0.14, 0.16, 31),
        ("刘洋", 0.09, 0.10, 27),
    ]
    reps = [
        {
            "id": i + 1,
            "name": name,
            "revenue": round(scale * rev / 1000) * 1000,
            "target": round(scale * 0.24 / 1000) * 1000,
            "deals": max(1, round(36 * d)),
            "win_rate": wr,
            "rank": i + 1,
        }
        for i, (name, rev, d, wr) in enumerate(raw)
    ]
    reps.sort(key=lambda r: r["revenue"], reverse=True)
    for i, r in enumerate(reps):
        r["rank"] = i + 1
    return reps


@router.get("/performance")
def performance(period: str = "month") -> dict[str, Any]:
    prof = _PERIOD_PROFILE.get(period, _PERIOD_PROFILE["month"])
    completion = round(prof["actual"] / prof["target"] * 1000) / 10
    avg = round(prof["actual"] / prof["deals"])
    return {
        "success": True,
        "data": {
            "period": period,
            "revenue_target": prof["target"],
            "revenue_actual": prof["actual"],
            "completion_rate": completion,
            "deals_closed": prof["deals"],
            "avg_deal_size": avg,
            "momentum_pct": prof["momentum"],
            "win_rate": 38,
            "pipeline_value": round(prof["target"] * 1.8),
            "forecast": round(prof["actual"] * 1.32),
            "reps": _build_reps(prof["actual"]),
            "revenue_trend": [
                {"period": "第1周", "target": round(prof["target"] / 4), "actual": round(prof["actual"] / 2.6 * 0.85)},
                {"period": "第2周", "target": round(prof["target"] / 4), "actual": round(prof["actual"] / 2.6 * 1.05)},
                {"period": "第3周", "target": round(prof["target"] / 4), "actual": round(prof["actual"] / 2.6 * 0.95)},
                {"period": "第4周", "target": round(prof["target"] / 4), "actual": 0},
            ],
            "goals": [
                {
                    "id": "g1",
                    "title": f"{prof['label']}签约目标",
                    "target": 30,
                    "actual": prof["deals"],
                    "unit": "单",
                    "breakdown": [
                        {"period": "第1周", "target": 8, "actual": 3, "progress": 37.5},
                        {"period": "第2周", "target": 8, "actual": 4, "progress": 50},
                        {"period": "第3周", "target": 7, "actual": 3, "progress": 42.9},
                        {"period": "第4周", "target": 7, "actual": 2, "progress": 28.6},
                    ],
                }
            ],
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
