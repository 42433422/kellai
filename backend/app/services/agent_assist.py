"""Local agent-assist loop: knowledge recommendations, risk hints, and intake autofill."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.services.growth_loop import customer_agent_operating_insight, customer_message_context
from app.services.knowledge_base import search_articles
from app.services.message_store import get_messages
from app.services.pipeline import _stage_rank, load_pipeline, normalize_stage_id, save_pipeline
from app.services.quality_inspection import inspect_customer_conversation


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truthy_match(text: str, keywords: tuple[str, ...]) -> bool:
    return any(key in text for key in keywords)


def _extract_phone(text: str) -> str:
    match = re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", text)
    return match.group(1) if match else ""


def _extract_email(text: str) -> str:
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return match.group(0) if match else ""


def _compact(text: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit]


def _display_name(doc: dict[str, Any], ctx: dict[str, Any]) -> str:
    for key in ("name", "display_name", "username"):
        value = str(doc.get(key) or ctx.get(key) or "").strip()
        if value:
            return value
    return str(ctx.get("customer_name") or f"客户{doc.get('customer_id') or ''}").strip()


def _build_draft(customer_id: int, doc: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    messages = get_messages(int(customer_id), limit=30)
    inbound = [msg for msg in messages if str(msg.direction or "") == "inbound"]
    latest_inbound = inbound[0] if inbound else None
    joined = "\n".join(str(msg.content or "") for msg in inbound[:8])
    source_text = joined or str(ctx.get("last_message_preview") or "")

    requirement_parts: list[str] = []
    if latest_inbound and str(latest_inbound.content or "").strip():
        requirement_parts.append(str(latest_inbound.content).strip())
    memory = str(ctx.get("memory_summary") or "").strip()
    if memory:
        requirement_parts.append(memory)

    company = str(doc.get("company") or "").strip()
    if not company:
        match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9]{2,24}(?:公司|门店|店|机构|团队))", source_text)
        candidate = match.group(1) if match else ""
        company = "" if candidate.startswith(("个", "家")) else candidate

    need_mobile = _truthy_match(source_text, ("小程序", "手机", "微信", "移动", "企微", "私域"))
    desktop_needed = "需要" if _truthy_match(source_text, ("CRM", "后台", "电脑", "桌面", "坐席", "客服系统", "管理")) else "待确认"

    return {
        "contact_name": _display_name(doc, ctx),
        "contact_email": str(doc.get("email") or _extract_email(source_text) or "").strip(),
        "contact_phone": str(doc.get("phone") or _extract_phone(source_text) or "").strip(),
        "company_name": company,
        "requirement_desc": _compact("；".join(requirement_parts) or "客户已进线，待补充需求。", 260),
        "desktop_system_needed": desktop_needed,
        "need_mobile": need_mobile,
        "submitted_at": _now_iso(),
        "autofill_source": "agent_assist",
        "source_message_ids": [str(msg.id) for msg in inbound[:5]],
        "field_confidence": {
            "contact_name": 0.7 if _display_name(doc, ctx) else 0.2,
            "contact_email": 0.9 if (doc.get("email") or _extract_email(source_text)) else 0.1,
            "contact_phone": 0.9 if (doc.get("phone") or _extract_phone(source_text)) else 0.1,
            "company_name": 0.8 if company else 0.2,
            "requirement_desc": 0.85 if requirement_parts else 0.35,
            "need_mobile": 0.75 if need_mobile else 0.45,
        },
    }


def _timeline_entry(status: str) -> dict[str, Any]:
    return {
        "stage": "intake_done" if status == "applied" else "intake",
        "at": _now_iso(),
        "source": "agent_assist",
        "note": "坐席助手已自动抽取需求表单并生成知识/风险建议。",
    }


def build_agent_assist(customer_id: int, *, persist: bool = False, actor: str = "system") -> dict[str, Any]:
    """Build or apply a local agent-assist package for one customer."""

    uid = int(customer_id)
    doc = load_pipeline(uid)
    ctx = customer_message_context(uid)
    insight = customer_agent_operating_insight(uid)
    quality = inspect_customer_conversation(uid)
    draft = _build_draft(uid, doc, ctx)

    query = " ".join(
        part
        for part in [
            str(draft.get("requirement_desc") or ""),
            str(ctx.get("next_action") or ""),
            str(insight.get("memory_summary") or ""),
        ]
        if part
    )
    knowledge = search_articles(query or "企微 接入 交付 优惠", limit=3)

    risk_items: list[dict[str, Any]] = []
    for item in insight.get("risk_signals") or []:
        if isinstance(item, dict):
            risk_items.append(
                {
                    "key": str(item.get("key") or ""),
                    "label": str(item.get("label") or ""),
                    "severity": "medium",
                    "evidence": str(item.get("matched") or ""),
                }
            )
    for rule in quality.get("failed_rules") or []:
        if isinstance(rule, dict):
            risk_items.append(
                {
                    "key": str(rule.get("key") or ""),
                    "label": str(rule.get("label") or ""),
                    "severity": str(rule.get("severity") or "low"),
                    "evidence": str(rule.get("matched") or rule.get("evidence") or ""),
                }
            )
    deduped_risks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in risk_items:
        key = item.get("key") or item.get("label")
        if key in seen:
            continue
        seen.add(str(key))
        deduped_risks.append(item)

    missing_fields = [
        label
        for field, label in [
            ("contact_phone", "联系电话"),
            ("company_name", "公司/门店"),
            ("requirement_desc", "需求描述"),
        ]
        if not str(draft.get(field) or "").strip()
    ]
    next_actions = [
        str(ctx.get("next_action") or "").strip() or "确认客户预算、上线时间和负责人。",
        "按自动填单结果补齐需求表，生成报价前先确认缺失字段。",
    ]
    if deduped_risks:
        next_actions.append("先处理风险提醒，再让 AI 继续自动回复。")
    if knowledge:
        next_actions.append("回复时引用推荐知识，保持服务口径一致。")

    status = "draft"
    saved_pipeline: dict[str, Any] | None = None
    if persist:
        doc["intake_form"] = draft
        doc["intake_submitted_at"] = draft["submitted_at"]
        doc["agent_assist"] = {
            "status": "applied",
            "applied_at": _now_iso(),
            "actor": str(actor or "system")[:80],
            "knowledge_ids": [str(item.get("id") or "") for item in knowledge],
            "risk_count": len(deduped_risks),
            "missing_fields": missing_fields,
        }
        stage = normalize_stage_id(str(doc.get("stage") or "idle"))
        if _stage_rank(stage) < _stage_rank("intake_done"):
            doc["stage"] = "intake_done"
        timeline = list(doc.get("timeline") or [])
        timeline.append(_timeline_entry("applied"))
        doc["timeline"] = timeline[-30:]
        saved_pipeline = save_pipeline(doc)
        status = "applied"

    return {
        "customer_id": uid,
        "status": status,
        "persisted": bool(persist),
        "draft": draft,
        "missing_fields": missing_fields,
        "knowledge_recommendations": knowledge,
        "risk_alerts": deduped_risks[:6],
        "next_actions": [item for item in next_actions if item],
        "quality_score": quality.get("score"),
        "message_count": ctx.get("message_count"),
        "pipeline_stage": (saved_pipeline or doc).get("stage"),
        "applied_at": (saved_pipeline or doc).get("agent_assist", {}).get("applied_at") if isinstance((saved_pipeline or doc).get("agent_assist"), dict) else "",
        "passed": bool(str(draft.get("requirement_desc") or "").strip()) and bool(knowledge or deduped_risks or next_actions),
    }


def agent_assist_summary(customer_id: int) -> dict[str, Any]:
    doc = load_pipeline(int(customer_id))
    saved = doc.get("agent_assist") if isinstance(doc.get("agent_assist"), dict) else {}
    result = build_agent_assist(int(customer_id), persist=False)
    if saved:
        result["status"] = str(saved.get("status") or "applied")
        result["persisted"] = True
        result["applied_at"] = str(saved.get("applied_at") or "")
        if isinstance(doc.get("intake_form"), dict):
            result["draft"] = doc.get("intake_form")
    return result


__all__ = ["agent_assist_summary", "build_agent_assist"]
