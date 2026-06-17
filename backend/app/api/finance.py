"""v7 智能财务 API 桩实现。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/kellai/finance", tags=["finance"])


class AskBody(BaseModel):
    question: str = ""


_FIN_PERIOD = {
    "month": {"revenue": 1280000, "cost": 456000, "rev_g": 4.9, "cost_g": 3.6},
    "quarter": {"revenue": 3680000, "cost": 1340000, "rev_g": 11.2, "cost_g": 7.1},
    "year": {"revenue": 13600000, "cost": 5020000, "rev_g": 18.0, "cost_g": 9.4},
}


@router.get("/dashboard")
def dashboard(period: str = "month") -> dict:
    prof = _FIN_PERIOD.get(period, _FIN_PERIOD["month"])
    profit = prof["revenue"] - prof["cost"]
    margin = round(profit / prof["revenue"] * 1000) / 10
    scale = prof["revenue"] / 1280000
    return {
        "success": True,
        "data": {
            "period": period,
            "revenue": prof["revenue"],
            "cost": prof["cost"],
            "profit": profit,
            "profit_margin": margin,
            "revenue_growth": prof["rev_g"],
            "cost_growth": prof["cost_g"],
            "profit_growth": round((prof["rev_g"] - prof["cost_g"]) * 10) / 10 + 2,
            "cash_flow": round(profit * 0.78),
            "receivable": round(prof["revenue"] * 0.32),
            "payable": round(prof["cost"] * 0.41),
            "channel_breakdown": [
                {"channel": "微信", "revenue": round(448000 * scale), "cost": round(120000 * scale), "profit": round(328000 * scale)},
                {"channel": "抖音", "revenue": round(384000 * scale), "cost": round(180000 * scale), "profit": round(204000 * scale)},
                {"channel": "企业微信", "revenue": round(256000 * scale), "cost": round(80000 * scale), "profit": round(176000 * scale)},
                {"channel": "邮件", "revenue": round(192000 * scale), "cost": round(76000 * scale), "profit": round(116000 * scale)},
            ],
            "monthly_trend": [
                {"month": "2026-01", "revenue": 980000, "cost": 380000, "profit": 600000},
                {"month": "2026-02", "revenue": 1050000, "cost": 400000, "profit": 650000},
                {"month": "2026-03", "revenue": 1120000, "cost": 420000, "profit": 700000},
                {"month": "2026-04", "revenue": 1180000, "cost": 430000, "profit": 750000},
                {"month": "2026-05", "revenue": 1220000, "cost": 440000, "profit": 780000},
                {"month": "2026-06", "revenue": 1280000, "cost": 456000, "profit": 824000},
            ],
        },
    }


@router.post("/ask")
def ask(body: AskBody) -> dict:
    q = body.question.lower()
    if "利润" in q or "profit" in q:
        ans = "本月利润 ¥824,000，利润率 64.4%，环比上月增长 5.6%。微信渠道利润贡献最高。"
    elif "成本" in q or "cost" in q or "费用" in q:
        ans = "本月总成本 ¥456,000（环比 +3.6%），抖音渠道占比最高（约 39%），建议优化投放。"
    elif "现金流" in q or "cash" in q:
        ans = "本月经营性现金流约 ¥642,000，应收 ¥409,600、应付 ¥186,960，现金流健康。"
    elif "渠道" in q:
        ans = "四大渠道利润：微信 > 抖音 > 企业微信 > 邮件，微信 ROI 最高(3.2x)。"
    elif "预算" in q:
        ans = "建议下月营销预算 ¥200,000：微信 ¥70K、抖音 ¥60K、企业微信 ¥40K、邮件 ¥30K。"
    elif "趋势" in q or "增长" in q or "同比" in q or "环比" in q:
        ans = "近 6 个月营收从 ¥980K 增至 ¥1.28M，月均增速约 5.5%，同比 +18%。"
    else:
        ans = f"关于「{body.question}」：本月营收 ¥1,280,000（同比 +18%），利润率 64.4%。"
    return {"success": True, "data": {"answer": ans}}


@router.get("/budget-suggest")
def budget_suggest() -> dict:
    return {
        "success": True,
        "data": {
            "total_budget": 200000,
            "allocations": [
                {"channel": "微信", "amount": 70000, "roi": 3.2, "reason": "ROI 最高，建议维持并适度加码"},
                {"channel": "抖音", "amount": 60000, "roi": 2.1, "reason": "量大但成本偏高，优化素材与定向"},
                {"channel": "企业微信", "amount": 40000, "roi": 2.8, "reason": "B2B 转化稳定，保持投入"},
                {"channel": "邮件", "amount": 30000, "roi": 1.8, "reason": "低成本触达老客户，做召回"},
            ],
        },
    }


@router.get("/performance")
def performance(period: str = "month") -> dict:
    scale = 3 if period == "quarter" else 12 if period == "year" else 1
    raw = [
        {"user_id": 1, "name": "张伟", "revenue": 285000, "deals": 8, "conversion_rate": 32, "target": 300000},
        {"user_id": 2, "name": "李娜", "revenue": 198000, "deals": 6, "conversion_rate": 28, "target": 220000},
        {"user_id": 3, "name": "王芳", "revenue": 156000, "deals": 5, "conversion_rate": 25, "target": 200000},
        {"user_id": 4, "name": "刘建", "revenue": 98000, "deals": 3, "conversion_rate": 18, "target": 150000},
        {"user_id": 5, "name": "赵敏", "revenue": 142000, "deals": 4, "conversion_rate": 22, "target": 160000},
        {"user_id": 6, "name": "孙浩", "revenue": 76000, "deals": 2, "conversion_rate": 15, "target": 120000},
    ]
    members: list[dict[str, Any]] = []
    for m in raw:
        revenue = m["revenue"] * scale
        target = m["target"] * scale
        members.append(
            {
                "user_id": m["user_id"],
                "name": m["name"],
                "revenue": revenue,
                "deals": m["deals"] * scale,
                "conversion_rate": m["conversion_rate"],
                "target": target,
                "attainment": round(revenue / target * 1000) / 10,
                "trend": [round(revenue * f) for f in (0.78, 0.85, 0.82, 0.94, 0.97, 1.0)],
                "rank": 0,
            }
        )
    members.sort(key=lambda x: x["revenue"], reverse=True)
    for i, m in enumerate(members):
        m["rank"] = i + 1
    return {"success": True, "data": members}


@router.get("/alerts")
def alerts() -> dict:
    return {
        "success": True,
        "data": [
            {"id": "fa1", "type": "cost_overrun", "severity": "high", "title": "抖音渠道成本超标", "message": "本月抖音投放成本超出预算 15%", "timestamp": "2026-06-13T10:00:00Z", "read": False},
            {"id": "fa2", "type": "channel_anomaly", "severity": "medium", "title": "邮件渠道转化率下降", "message": "邮件打开率周环比下降 12%", "timestamp": "2026-06-13T04:00:00Z", "read": False},
            {"id": "fa3", "type": "profit_drop", "severity": "medium", "title": "企业微信毛利率波动", "message": "企业微信毛利率较上周下降 3.2pct", "timestamp": "2026-06-12T10:00:00Z", "read": False},
            {"id": "fa4", "type": "channel_anomaly", "severity": "low", "title": "应收账款临近账期", "message": "3 笔应收（合计 ¥86,000）将于 7 天内到期", "timestamp": "2026-06-11T10:00:00Z", "read": False},
        ],
    }


@router.get("/report")
def report(period: str = "2026-06") -> dict:
    csv = "%0A".join(
        [
            "month,revenue,cost,profit,profit_margin",
            "2026-05,1220000,440000,780000,63.9",
            "2026-06,1280000,456000,824000,64.4",
        ]
    )
    return {
        "success": True,
        "data": {
            "id": "rpt_1",
            "title": f"{period} 财务报表",
            "period": period,
            "generated_at": "2026-06-13T00:00:00Z",
            "download_url": f"data:text/csv;charset=utf-8,{csv}",
        },
    }


@router.post("/decision")
def decision() -> dict:
    return {
        "success": True,
        "data": {
            "summary": "建议优先优化抖音投放效率，加大微信渠道投入，并加速应收回款以改善现金流",
            "actions": [
                {"title": "优化抖音素材", "description": "A/B 测试新短视频脚本，目标将 CPC 降低 12%", "priority": "high"},
                {"title": "增加微信预算 10%", "description": "微信 ROI 3.2x，仍有增长空间", "priority": "medium"},
                {"title": "加速应收回款", "description": "对 3 笔临期应收（¥86K）提前跟进", "priority": "medium"},
                {"title": "启动邮件召回", "description": "对 30 天未活跃客户发送专属优惠", "priority": "low"},
            ],
        },
    }
