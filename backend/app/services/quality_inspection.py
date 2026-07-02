"""Deterministic customer-service quality inspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.growth_loop import customer_message_context
from app.services.message_store import get_messages


@dataclass(frozen=True)
class QualityRule:
    key: str
    label: str
    severity: str
    direction: str
    keywords: tuple[str, ...]
    penalty: int
    recommendation: str


_RULES: tuple[QualityRule, ...] = (
    QualityRule(
        key="compliance_promise",
        label="过度承诺/合规风险",
        severity="high",
        direction="outbound",
        keywords=("绝对", "百分百", "100%", "保证", "包过", "无风险", "违规", "虚假", "私下转账", "刷单"),
        penalty=30,
        recommendation="删除绝对化承诺，改为明确交付条件、时间边界和人工确认口径。",
    ),
    QualityRule(
        key="negative_sentiment",
        label="客户负面情绪",
        severity="high",
        direction="inbound",
        keywords=("投诉", "差评", "生气", "不满意", "太慢", "骗人", "乱承诺", "失望"),
        penalty=24,
        recommendation="优先安抚客户，承认问题并给出明确处理时限。",
    ),
    QualityRule(
        key="refund_risk",
        label="退款/流失风险",
        severity="high",
        direction="inbound",
        keywords=("退款", "退钱", "取消", "不要了", "终止合作"),
        penalty=20,
        recommendation="同步主管介入，补充补救方案和可执行的保留策略。",
    ),
    QualityRule(
        key="handoff_required",
        label="需要人工/主管介入",
        severity="medium",
        direction="inbound",
        keywords=("人工", "主管", "负责人", "老板", "经理", "电话联系"),
        penalty=12,
        recommendation="生成主管待办，并把客户诉求、最近消息和风险原因带过去。",
    ),
    QualityRule(
        key="price_objection",
        label="价格异议",
        severity="medium",
        direction="inbound",
        keywords=("太贵", "优惠", "折扣", "便宜", "预算", "价格高", "能不能少"),
        penalty=8,
        recommendation="补充套餐差异和 ROI 依据，必要时给出可审批优惠边界。",
    ),
)


def _normalize_direction(direction: str) -> str:
    value = str(direction or "").strip().lower()
    if value in {"in", "incoming", "customer"}:
        return "inbound"
    if value in {"out", "outgoing", "agent", "assistant"}:
        return "outbound"
    return value or "inbound"


def _message_dict(message: Any) -> dict[str, str]:
    return {
        "id": str(getattr(message, "id", "") or ""),
        "direction": _normalize_direction(str(getattr(message, "direction", "") or "")),
        "content": str(getattr(message, "content", "") or ""),
        "created_at": str(getattr(message, "created_at", "") or ""),
        "channel_type": str(getattr(message, "channel_type", "") or ""),
    }


def _matched_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword and keyword in text]


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def inspect_customer_conversation(customer_id: int, *, limit: int = 120) -> dict[str, Any]:
    """Inspect persisted customer messages and return a supervisor-ready report."""
    uid = int(customer_id)
    ctx = customer_message_context(uid)
    raw_messages = [_message_dict(msg) for msg in get_messages(uid, limit=limit)]
    messages = sorted(raw_messages, key=lambda item: item.get("created_at") or "")
    inbound = [item for item in messages if item["direction"] == "inbound"]
    outbound = [item for item in messages if item["direction"] == "outbound"]

    failed_rules: list[dict[str, Any]] = []
    recommendations: list[str] = []
    penalties = 0
    seen_rules: set[str] = set()

    if not messages:
        failed_rules.append(
            {
                "key": "no_conversation",
                "label": "没有可质检的客户会话",
                "severity": "medium",
                "matched": "",
                "evidence": "",
            }
        )
        recommendations.append("先接入真实渠道消息，或用模拟客户行为生成完整会话后再质检。")
        penalties += 35

    if inbound and not outbound:
        failed_rules.append(
            {
                "key": "no_response",
                "label": "客户进线后未回复",
                "severity": "high",
                "matched": "",
                "evidence": inbound[-1]["content"][:160],
            }
        )
        recommendations.append("立即补一条人工或 AI 回复，并设置跟进提醒。")
        penalties += 25
        seen_rules.add("no_response")

    last_inbound_at = inbound[-1]["created_at"] if inbound else ""
    last_outbound_at = outbound[-1]["created_at"] if outbound else ""
    unanswered_inbound = bool(last_inbound_at and (not last_outbound_at or last_inbound_at > last_outbound_at))
    if unanswered_inbound and "no_response" not in seen_rules:
        failed_rules.append(
            {
                "key": "unanswered_latest_inbound",
                "label": "最后一条客户消息未闭环",
                "severity": "medium",
                "matched": "",
                "evidence": inbound[-1]["content"][:160],
            }
        )
        recommendations.append("优先回复最后一条客户消息，并在回复中确认下一步责任人和时间。")
        penalties += 14
        seen_rules.add("unanswered_latest_inbound")

    for rule in _RULES:
        candidates = [item for item in messages if item["direction"] == rule.direction or rule.direction == "any"]
        evidence = ""
        matched: list[str] = []
        for item in candidates:
            matched = _matched_keywords(item["content"], rule.keywords)
            if matched:
                evidence = item["content"][:160]
                break
        if not matched:
            continue
        failed_rules.append(
            {
                "key": rule.key,
                "label": rule.label,
                "severity": rule.severity,
                "matched": "、".join(matched[:6]),
                "evidence": evidence,
            }
        )
        recommendations.append(rule.recommendation)
        penalties += rule.penalty

    unique_recommendations: list[str] = []
    for item in recommendations:
        if item not in unique_recommendations:
            unique_recommendations.append(item)

    response_coverage = 1.0
    if inbound:
        response_coverage = min(1.0, len(outbound) / max(len(inbound), 1))
    score = max(0, min(100, 100 - penalties))
    severity_order = {"high": 3, "medium": 2, "low": 1}
    high_risk_count = sum(1 for item in failed_rules if item.get("severity") == "high")
    review_required = bool(score < 80 or high_risk_count > 0 or unanswered_inbound)
    risk_level = "high" if high_risk_count > 0 or score < 60 else "medium" if review_required else "low"

    if not unique_recommendations:
        unique_recommendations.append("当前会话无明显质检风险，保持标准回复节奏并继续沉淀知识库。")

    failed_rules.sort(key=lambda item: severity_order.get(str(item.get("severity") or ""), 0), reverse=True)
    summary = (
        f"{ctx.get('customer_name') or f'客户{uid}'} 质检得分 {score}，"
        f"共检查 {len(messages)} 条消息，命中 {len(failed_rules)} 项规则。"
    )
    if review_required:
        summary += " 建议主管复核后再继续自动跟进。"

    return {
        "customer_id": uid,
        "customer_name": ctx.get("customer_name") or f"客户{uid}",
        "score": score,
        "grade": _grade(score),
        "review_required": review_required,
        "risk_level": risk_level,
        "message_count": len(messages),
        "inbound_count": len(inbound),
        "outbound_count": len(outbound),
        "response_coverage": round(response_coverage, 2),
        "unanswered_inbound": unanswered_inbound,
        "failed_rules": failed_rules,
        "recommendations": unique_recommendations[:6],
        "manager_report": {
            "summary": summary,
            "coaching_points": unique_recommendations[:3],
            "suggested_action": (
                "主管介入复盘话术并安排补救跟进" if review_required else "继续自动跟进并抽样复查"
            ),
            "risk_level": risk_level,
        },
    }


__all__ = ["inspect_customer_conversation"]
