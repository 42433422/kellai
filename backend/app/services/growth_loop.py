"""Lead-to-follow-up loop wiring for messages, customers, and pipeline."""

from __future__ import annotations

import logging
from typing import Any

from app.channels.base import UnifiedMessage
from app.services.pipeline import (
    _STAGE_ORDER,
    _append_timeline,
    _customer_id_from_doc,
    _display_name_from_doc,
    _iter_pipeline_docs,
    _stage_rank,
    create_customer,
    load_pipeline,
    normalize_stage_id,
    save_pipeline,
)

logger = logging.getLogger(__name__)


def _normalize_direction(direction: str) -> str:
    value = str(direction or "").strip().lower()
    if value in {"in", "incoming", "inbound", "customer"}:
        return "inbound"
    if value in {"out", "outgoing", "outbound", "agent", "assistant"}:
        return "outbound"
    return value or "inbound"


def _channel_contacts(doc: dict[str, Any]) -> dict[str, str]:
    raw = doc.get("channel_contacts")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if str(v).strip()}
    return {}


def _demo_source_from_message(msg: UnifiedMessage) -> str:
    metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
    simulated = metadata.get("simulated")
    is_simulated = simulated is True or simulated == 1 or str(simulated).strip().lower() in {
        "true",
        "yes",
    }
    source = str(metadata.get("source") or "").strip().lower()
    if source in {"closed_loop_audit", "llm_full_flow"}:
        return source
    return "simulation" if is_simulated else ""


def resolve_customer_for_message(msg: UnifiedMessage) -> dict[str, Any]:
    """Find or create the customer pipeline touched by a channel message."""
    demo_source = _demo_source_from_message(msg)
    metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
    message_team_id = int(metadata.get("team_id") or 0)
    if int(msg.customer_id or 0) > 0:
        doc = load_pipeline(int(msg.customer_id))
    else:
        contact_id = str(msg.contact_id or "").strip()
        channel_type = str(msg.channel_type or "").strip()
        doc = {}
        for candidate in _iter_pipeline_docs():
            candidate_team_id = int(candidate.get("team_id") or 0)
            if message_team_id > 0 and candidate_team_id not in {0, message_team_id}:
                continue
            contacts = _channel_contacts(candidate)
            if channel_type and contact_id and contacts.get(channel_type) == contact_id:
                doc = candidate
                break
            if contact_id and str(candidate.get("contact_id") or "") == contact_id:
                doc = candidate
                break
        if not doc:
            display_name = str(msg.contact_name or msg.contact_id or "新线索").strip()
            doc = create_customer(
                {
                    "name": display_name,
                    "source": channel_type,
                    "stage": "connected" if _normalize_direction(msg.direction) == "inbound" else "idle",
                    "channel_sources": [channel_type] if channel_type else [],
                    "tags": ["自动接入"],
                    "is_demo": bool(demo_source),
                },
                username=display_name,
            )

    if message_team_id > 0:
        doc["team_id"] = message_team_id
    contacts = _channel_contacts(doc)
    if msg.channel_type and msg.contact_id:
        contacts[str(msg.channel_type)] = str(msg.contact_id)
        doc["channel_contacts"] = contacts
    if msg.contact_name and not doc.get("name"):
        doc["name"] = str(msg.contact_name).strip()
    if demo_source:
        doc["is_demo"] = True
        doc["demo_source"] = demo_source
    return doc


def _keyword_intent(content: str) -> dict[str, Any]:
    """Local-only intent detection. It deliberately avoids LLM calls."""
    try:
        from app.services.ai_copilot import HIGH_INTENT_TYPES, INTENT_LABELS, _keyword_match_intent

        intent, confidence, keywords = _keyword_match_intent(content)
        return {
            "intent": intent,
            "intent_label": INTENT_LABELS.get(intent, intent),
            "confidence": confidence,
            "keywords": keywords,
            "is_high_intent": intent in HIGH_INTENT_TYPES,
        }
    except Exception:
        logger.debug("本地意图识别失败", exc_info=True)
        return {
            "intent": "other",
            "intent_label": "其他",
            "confidence": 0.0,
            "keywords": [],
            "is_high_intent": False,
        }


def _infer_stage(current_stage: str, content: str, direction: str, intent: str) -> tuple[str, str]:
    """Infer the next pipeline stage without downgrading existing progress."""
    stage = normalize_stage_id(current_stage)
    if stage not in _STAGE_ORDER:
        stage = "idle"
    text = str(content or "")
    target = stage
    note = ""

    if direction == "outbound":
        if _stage_rank(stage) <= _stage_rank("idle"):
            target = "connected"
            note = "已主动回复客户"
        return target, note

    if _stage_rank(stage) <= _stage_rank("idle"):
        target = "connected"
        note = "客户已进线，自动建联"

    signed_keywords = ("已付", "付款了", "已付款", "已打款", "打款了", "已签", "签好了", "合同确认", "成交")
    if any(k in text for k in signed_keywords):
        if _stage_rank(target) < _stage_rank("signed"):
            target = "signed"
            note = "客户反馈已签约/付款"
    elif _looks_like_negotiation(text) and _stage_rank(target) >= _stage_rank("quoted"):
        if _stage_rank(target) < _stage_rank("negotiating"):
            target = "negotiating"
            note = "客户提出价格异议，进入议价"
    elif any(k in text for k in ("已提交", "填好了", "提交了", "需求表", "表单")):
        if _stage_rank(target) < _stage_rank("intake_done"):
            target = "intake_done"
            note = "客户已反馈需求资料"
    elif _looks_like_requirement_detail(text):
        if _stage_rank(target) < _stage_rank("intake_done"):
            target = "intake_done"
            note = "客户已补充关键需求信息"
    elif any(k in text for k in ("合同", "签约", "签合同", "下单", "付款", "打款")):
        if _stage_rank(target) < _stage_rank("contract_pending"):
            target = "contract_pending"
            note = "客户进入签约/付款沟通"
    elif any(k in text for k in ("怎么买", "购买", "求链接", "链接", "加微信", "详细说")):
        if _stage_rank(target) < _stage_rank("intake"):
            target = "intake"
            note = "社媒客户表达购买/加微意向，进入需求采集"
    elif intent == "negotiation" and _stage_rank(target) >= _stage_rank("quoted"):
        if _stage_rank(target) < _stage_rank("negotiating"):
            target = "negotiating"
            note = "客户提出价格异议，进入议价"
    elif intent in {"inquiry", "negotiation", "interest", "urgent"}:
        if _stage_rank(target) < _stage_rank("intake"):
            target = "intake"
            note = "客户高意向咨询，进入需求采集"

    return target, note


def _looks_like_requirement_detail(text: str) -> bool:
    """Detect a customer message that contains enough需求信息 to move beyond intake."""
    if not text:
        return False
    markers = (
        "门店", "账号", "员工", "客服", "消息", "线索", "客资", "预算", "行业", "每天",
        "日均", "抖音", "小红书", "企微", "企业微信", "微信", "小程序", "拼多多", "淘宝",
        "需求", "场景", "套餐",
    )
    hits = sum(1 for marker in markers if marker in text)
    return hits >= 2


def _looks_like_negotiation(text: str) -> bool:
    if not text:
        return False
    return any(k in text for k in ("太贵", "有点贵", "优惠", "折扣", "便宜", "降价", "让利", "能不能少", "价格高"))


def _next_action(stage: str, intent_label: str, direction: str) -> str:
    if direction == "outbound":
        return "等待客户反馈，必要时设置下次跟进提醒"
    actions = {
        "idle": "主动建联，发送欢迎语",
        "connected": "补齐客户需求，确认预算/时间/负责人",
        "intake": "发送需求采集或直接整理报价要点",
        "intake_done": "生成报价方案并安排下一次沟通",
        "quoted": "跟进报价反馈，处理异议",
        "negotiating": "确认优惠边界并推进签约",
        "contract_pending": "确认合同/付款节点",
        "signed": "安排交付并同步客户预期",
        "delivering": "跟进交付进度",
        "delivered": "回访满意度并挖掘复购",
    }
    base = actions.get(stage, "主动跟进客户")
    if intent_label and intent_label not in {"其他", "闲聊"}:
        return f"{base}（客户意图：{intent_label}）"
    return base


def apply_message_to_growth_loop(msg: UnifiedMessage) -> dict[str, Any]:
    """Apply a saved/received message to customer profile, pipeline, and reminders."""
    direction = _normalize_direction(msg.direction)
    doc = resolve_customer_for_message(msg)
    uid = _customer_id_from_doc(doc)
    content = str(msg.content or "").strip()
    channel_type = str(msg.channel_type or "").strip()
    created_at = str(msg.created_at or "")

    if channel_type:
        sources = [str(x) for x in (doc.get("channel_sources") or []) if str(x).strip()]
        if channel_type not in sources:
            sources.append(channel_type)
        doc["channel_sources"] = sources

    if content:
        doc["last_message_preview"] = content[:500]
    doc["last_message_at"] = created_at

    intent = _keyword_intent(content) if content and direction == "inbound" else {
        "intent": "other",
        "intent_label": "其他",
        "confidence": 0.0,
        "keywords": [],
        "is_high_intent": False,
    }

    if direction == "inbound":
        doc["last_inbound_at"] = created_at
        doc["pending_follow_up"] = True
        doc["last_intent"] = intent["intent"]
        doc["last_intent_label"] = intent["intent_label"]
        doc["last_intent_confidence"] = intent["confidence"]
        if intent["is_high_intent"]:
            tags = [str(t) for t in (doc.get("ai_tags") or []) if str(t).strip()]
            for tag in ("高意向", str(intent["intent_label"])):
                if tag and tag not in tags:
                    tags.append(tag)
            doc["ai_tags"] = tags[:12]
    elif direction == "outbound":
        doc["last_outbound_at"] = created_at
        doc["pending_follow_up"] = False

    before_stage = str(doc.get("stage") or "idle")
    target_stage, stage_note = _infer_stage(before_stage, content, direction, str(intent["intent"]))
    if target_stage != before_stage:
        doc["stage"] = target_stage
        _append_timeline(doc, target_stage, "growth_loop", note=stage_note)

    doc["next_action"] = _next_action(str(doc.get("stage") or "idle"), str(intent["intent_label"]), direction)
    doc["follow_up_reason"] = "客户有新消息待处理" if direction == "inbound" else ""

    try:
        from app.services.ai_copilot import calculate_ai_score
        from app.services.message_store import get_messages

        history = [
            {"content": m.content, "direction": m.direction, "created_at": m.created_at}
            for m in get_messages(uid, limit=30)
        ]
        doc["ai_score"] = calculate_ai_score(uid, messages=history)
    except Exception:
        logger.debug("更新客户 AI 评分失败: customer_id=%s", uid, exc_info=True)

    saved = save_pipeline(doc)
    return {
        "customer_id": uid,
        "customer_name": _display_name_from_doc(saved),
        "stage": str(saved.get("stage") or "idle"),
        "stage_label": _stage_label(str(saved.get("stage") or "idle")),
        "ai_score": float(saved.get("ai_score") or 0.0),
        "ai_intent": intent["intent_label"],
        "pending_follow_up": bool(saved.get("pending_follow_up")),
        "next_action": str(saved.get("next_action") or ""),
    }


def _stage_label(stage: str) -> str:
    from app.services.pipeline import PIPELINE_STAGES

    labels = {s["id"]: s["label"] for s in PIPELINE_STAGES}
    return labels.get(stage, stage)


def customer_message_context(customer_id: int) -> dict[str, Any]:
    doc = load_pipeline(int(customer_id))
    return {
        "customer_id": int(customer_id),
        "customer_name": _display_name_from_doc(doc),
        "stage": str(doc.get("stage") or "idle"),
        "stage_label": _stage_label(str(doc.get("stage") or "idle")),
        "ai_score": float(doc.get("ai_score") or 0.0),
        "ai_intent": str(doc.get("last_intent_label") or ""),
        "pending_follow_up": bool(doc.get("pending_follow_up")),
        "next_action": str(doc.get("next_action") or ""),
        "channel_sources": [str(x) for x in (doc.get("channel_sources") or []) if str(x).strip()],
        "channel_contacts": _channel_contacts(doc),
        "last_message_preview": str(doc.get("last_message_preview") or ""),
        "tags": [str(x) for x in (doc.get("tags") or []) if str(x).strip()],
        "ai_tags": [str(x) for x in (doc.get("ai_tags") or []) if str(x).strip()],
    }


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _risk_signals(text: str) -> list[dict[str, str]]:
    rules: list[tuple[str, str, tuple[str, ...]]] = [
        ("negative_sentiment", "客户负面情绪", ("生气", "投诉", "差评", "不满意", "太慢", "乱承诺", "骗人", "退款")),
        ("compliance_risk", "承诺/合规风险", ("保证", "百分百", "绝对", "包过", "违规", "禁用词", "虚假")),
        ("price_objection", "价格异议", ("太贵", "有点贵", "优惠", "折扣", "便宜", "降价", "价格高")),
        ("handoff_needed", "需要人工介入", ("人工", "负责人", "主管", "老板", "投诉", "合同", "退款")),
    ]
    found: list[dict[str, str]] = []
    for key, label, keywords in rules:
        matched = [kw for kw in keywords if kw in text]
        if matched:
            found.append({"key": key, "label": label, "matched": "、".join(matched[:6])})
    return found


def _management_insights(text: str, channels: list[str], messages: list[Any]) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []
    if len(channels) >= 2:
        insights.append(
            {
                "key": "omnichannel_one_id",
                "label": "跨渠道 One ID 已形成",
                "value": " / ".join(channels),
            }
        )
    if _contains_any(text, ("竞品", "对比", "别家", "同行", "替代")):
        insights.append({"key": "competitor_signal", "label": "客户正在对比竞品", "value": "建议销售给出差异化方案"})
    if _contains_any(text, ("太贵", "优惠", "折扣", "预算", "价格")):
        insights.append({"key": "pricing_signal", "label": "价格敏感客户", "value": "可准备阶梯套餐或限时优惠"})
    if _contains_any(text, ("差评", "投诉", "不满意", "退款", "太慢")):
        insights.append({"key": "quality_signal", "label": "服务质量风险", "value": "建议主管复核话术并优先介入"})
    inbound_count = sum(1 for msg in messages if _normalize_direction(getattr(msg, "direction", "")) == "inbound")
    if inbound_count >= 2:
        insights.append({"key": "active_customer", "label": "客户多轮主动咨询", "value": f"{inbound_count} 轮入站消息"})
    return insights


def customer_agent_operating_insight(customer_id: int) -> dict[str, Any]:
    """Generate a RedBear-like service operating insight from real customer data.

    The output is intentionally deterministic: it can be used by audits, UI panels,
    and tests without requiring an LLM key, while still reflecting persisted messages.
    """
    customer_id = int(customer_id)
    doc = load_pipeline(customer_id)
    ctx = customer_message_context(customer_id)
    from app.services.message_store import get_messages

    messages = get_messages(customer_id, limit=80)
    text = "\n".join(str(getattr(msg, "content", "") or "") for msg in messages)
    channels = [str(x) for x in (doc.get("channel_sources") or []) if str(x).strip()]
    risks = _risk_signals(text)
    insights = _management_insights(text, channels, messages)
    last_inbound = next(
        (msg for msg in messages if _normalize_direction(getattr(msg, "direction", "")) == "inbound"),
        None,
    )
    active_task = str(ctx.get("next_action") or "").strip()
    if risks:
        active_task = f"优先处理{risks[0]['label']}，{active_task or '安排人工跟进'}"
    memory_summary_parts = [
        f"{ctx.get('customer_name') or f'客户{customer_id}'} 当前处于{ctx.get('stage_label') or ctx.get('stage')}阶段",
    ]
    if channels:
        memory_summary_parts.append(f"已打通渠道：{' / '.join(channels)}")
    if ctx.get("ai_intent"):
        memory_summary_parts.append(f"最近意图：{ctx.get('ai_intent')}")
    if ctx.get("last_message_preview"):
        memory_summary_parts.append(f"最近消息：{ctx.get('last_message_preview')}")

    return {
        "customer_id": customer_id,
        "memory_summary": "；".join(memory_summary_parts),
        "channel_sources": channels,
        "channel_contacts": ctx.get("channel_contacts") or {},
        "last_inbound_preview": str(getattr(last_inbound, "content", "") or "")[:500] if last_inbound else "",
        "risk_signals": risks,
        "management_insights": insights,
        "active_task": active_task,
        "pending_follow_up": bool(ctx.get("pending_follow_up")),
        "ai_score": float(ctx.get("ai_score") or 0.0),
        "message_count": len(messages),
    }
