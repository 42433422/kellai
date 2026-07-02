"""Service learning loop from quality review, tickets, and knowledge base."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.growth_loop import customer_message_context
from app.services.knowledge_base import list_articles, search_articles, upsert_article
from app.services.message_store import get_messages
from app.services.quality_inspection import inspect_customer_conversation
from app.services.service_tickets import service_ticket_summary


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _article_id(customer_id: int) -> str:
    return f"service_learning_{int(customer_id)}"


def _existing_article(article_id: str) -> dict[str, Any] | None:
    for article in list_articles():
        if str(article.get("id") or "") == article_id:
            return article
    return None


def _rule_labels(report: dict[str, Any]) -> list[str]:
    rules = report.get("failed_rules") if isinstance(report.get("failed_rules"), list) else []
    labels: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        label = str(rule.get("label") or rule.get("key") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def _high_risk_count(report: dict[str, Any]) -> int:
    rules = report.get("failed_rules") if isinstance(report.get("failed_rules"), list) else []
    return sum(1 for item in rules if isinstance(item, dict) and str(item.get("severity") or "") == "high")


def _resolved_rehosted_tickets(summary: dict[str, Any]) -> list[dict[str, Any]]:
    tickets = summary.get("tickets") if isinstance(summary.get("tickets"), list) else []
    return [
        item
        for item in tickets
        if isinstance(item, dict)
        and str(item.get("status") or "") == "resolved"
        and bool(str(item.get("ai_rehost_action") or "").strip())
    ]


def _build_article_content(
    *,
    customer_id: int,
    context: dict[str, Any],
    quality: dict[str, Any],
    tickets: dict[str, Any],
    recommendations: list[str],
) -> str:
    latest_ticket = tickets.get("latest") if isinstance(tickets.get("latest"), dict) else {}
    rule_labels = _rule_labels(quality)
    manager_report = quality.get("manager_report") if isinstance(quality.get("manager_report"), dict) else {}
    resolution = str(latest_ticket.get("resolution") or "暂无已记录的人工处理结论。").strip()
    ai_rehost_action = str(latest_ticket.get("ai_rehost_action") or "处理完成后，AI 继续按合规口径跟进客户下一步。").strip()
    risk_text = "、".join(rule_labels) if rule_labels else "未命中高风险规则"
    recommendation_text = "\n".join(f"- {item}" for item in recommendations[:6]) or "- 保持标准回复节奏并持续抽样复查。"
    return (
        f"客户：{context.get('customer_name') or f'客户{customer_id}'}\n"
        f"当前阶段：{context.get('stage_label') or context.get('stage') or '-'}\n"
        f"质检得分：{quality.get('score')}，风险：{risk_text}\n"
        f"主管摘要：{manager_report.get('summary') or '-'}\n"
        f"工单处理：{resolution}\n"
        f"AI 回托口径：{ai_rehost_action}\n\n"
        "可复用 SOP：\n"
        f"{recommendation_text}\n"
        "- 回复客户时先确认诉求和情绪，再给出明确责任人、时间边界和下一步动作。\n"
        "- 避免绝对化承诺，把上线、退款、优惠、交付范围写成可核验条件。"
    )


def run_service_learning(customer_id: int, *, persist: bool = True) -> dict[str, Any]:
    """Turn a handled customer conversation into service metrics and reusable SOP."""
    uid = int(customer_id)
    context = customer_message_context(uid)
    messages = get_messages(uid, limit=120)
    quality = inspect_customer_conversation(uid)
    tickets = service_ticket_summary(uid)
    rehosted = _resolved_rehosted_tickets(tickets)
    rule_labels = _rule_labels(quality)
    recommendations = [
        str(item).strip()
        for item in (quality.get("recommendations") if isinstance(quality.get("recommendations"), list) else [])
        if str(item).strip()
    ]
    if rehosted:
        recommendations.append("将主管已确认的回托口径加入后续自动回复确认清单。")
    if rule_labels:
        recommendations.append("把命中的高风险规则作为客服培训抽查项。")

    unique_recommendations: list[str] = []
    for item in recommendations:
        if item not in unique_recommendations:
            unique_recommendations.append(item)
    if not unique_recommendations:
        unique_recommendations.append("当前会话无明显风险，继续沉淀高频问答和成交话术。")

    article_id = _article_id(uid)
    article_payload = {
        "id": article_id,
        "title": f"服务复盘：{context.get('customer_name') or f'客户{uid}'}",
        "content": _build_article_content(
            customer_id=uid,
            context=context,
            quality=quality,
            tickets=tickets,
            recommendations=unique_recommendations,
        ),
        "tags": ["服务复盘", "质检", "工单", "合规", "回托AI", *rule_labels][:20],
        "source": "service_learning",
    }
    article = upsert_article(article_payload) if persist else _existing_article(article_id)
    search_hits = search_articles(
        f"{article_id} {context.get('customer_name') or uid} 合规 工单 回托 质检 复盘",
        limit=3,
    )

    inbound_count = sum(1 for msg in messages if str(getattr(msg, "direction", "") or "") == "inbound")
    outbound_count = sum(1 for msg in messages if str(getattr(msg, "direction", "") or "") == "outbound")
    metrics = {
        "inspected_conversations": len(messages),
        "inbound_count": inbound_count,
        "outbound_count": outbound_count,
        "quality_score": quality.get("score"),
        "response_coverage": quality.get("response_coverage"),
        "high_risk_cases": _high_risk_count(quality),
        "ticket_total": tickets.get("total"),
        "ticket_open": tickets.get("open"),
        "ticket_resolved": tickets.get("resolved"),
        "ai_rehosted": len(rehosted),
        "kb_articles_created": 1 if article else 0,
        "top_risk_rules": rule_labels[:5],
    }
    passed = (
        len(messages) > 0
        and bool(unique_recommendations)
        and (not bool(quality.get("review_required")) or int(tickets.get("resolved") or 0) >= 1)
        and bool(article)
        and any(str(item.get("id") or "") == article_id for item in search_hits)
    )
    return {
        "customer_id": uid,
        "customer_name": context.get("customer_name") or f"客户{uid}",
        "generated_at": _now_iso(),
        "persisted": bool(persist and article),
        "passed": passed,
        "metrics": metrics,
        "recommendations": unique_recommendations[:8],
        "article": article,
        "article_preview": article_payload,
        "search_hits": search_hits,
        "quality": {
            "score": quality.get("score"),
            "grade": quality.get("grade"),
            "review_required": quality.get("review_required"),
            "risk_level": quality.get("risk_level"),
            "failed_rules": quality.get("failed_rules") or [],
        },
        "ticket_summary": {
            "total": tickets.get("total"),
            "open": tickets.get("open"),
            "resolved": tickets.get("resolved"),
            "latest": tickets.get("latest"),
        },
    }


__all__ = ["run_service_learning"]
