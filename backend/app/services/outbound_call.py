"""AI outbound call planning and simulated execution loop."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.channels.base import UnifiedMessage
from app.services.growth_loop import customer_agent_operating_insight, customer_message_context
from app.services.message_store import get_messages, save_message
from app.services.pipeline import _stage_rank, load_pipeline, normalize_stage_id, save_pipeline, set_pipeline_stage
from app.services.service_tickets import service_ticket_summary


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data_root() -> Path:
    from app.services.llm_config import _data_root as llm_data_root

    return llm_data_root()


def _calls_path() -> Path:
    return _data_root() / "outbound_calls.json"


def _read_disk() -> dict[str, Any]:
    path = _calls_path()
    if not path.is_file():
        return {"calls": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"calls": []}
    if not isinstance(data, dict):
        return {"calls": []}
    if not isinstance(data.get("calls"), list):
        data["calls"] = []
    return data


def _write_disk(data: dict[str, Any]) -> dict[str, Any]:
    path = _calls_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def _stage_label(stage: str) -> str:
    from app.services.pipeline import PIPELINE_STAGES

    labels = {item["id"]: item["label"] for item in PIPELINE_STAGES}
    return labels.get(stage, stage)


def _call_index(calls: list[dict[str, Any]], call_id: str) -> int:
    for index, item in enumerate(calls):
        if str(item.get("id") or "") == str(call_id):
            return index
    raise ValueError(f"未找到外呼任务: {call_id}")


def _purpose_from_stage(stage: str, purpose: str) -> str:
    value = str(purpose or "").strip()
    if value and value != "follow_up":
        return value[:64]
    rank = _stage_rank(stage)
    if rank >= _stage_rank("delivering"):
        return "delivery_review"
    if rank >= _stage_rank("signed"):
        return "delivery_confirm"
    if rank >= _stage_rank("contract_pending"):
        return "contract_close"
    if rank >= _stage_rank("quoted"):
        return "quote_follow_up"
    return "demo_invite"


def _script_for_call(context: dict[str, Any], insight: dict[str, Any], purpose: str) -> dict[str, Any]:
    stage_label = str(context.get("stage_label") or context.get("stage") or "未接触")
    customer_name = str(context.get("customer_name") or f"客户{context.get('customer_id') or ''}").strip()
    active_task = str(insight.get("active_task") or context.get("next_action") or "确认客户下一步").strip()
    memory = str(insight.get("memory_summary") or "").strip()
    openings = {
        "delivery_review": f"您好，我是客来来 AI 外呼助手，想确认 {customer_name} 当前交付使用情况和满意度。",
        "delivery_confirm": f"您好，我是客来来 AI 外呼助手，确认一下 {customer_name} 的上线交付资料是否齐全。",
        "contract_close": f"您好，我是客来来 AI 外呼助手，跟进一下合同和付款节点，方便现在确认吗？",
        "quote_follow_up": f"您好，我是客来来 AI 外呼助手，想同步报价方案并确认是否需要演示。",
        "demo_invite": f"您好，我是客来来 AI 外呼助手，看到您咨询过客来来，想帮您约一次产品演示。",
    }
    close_actions = {
        "delivery_review": "记录满意度，若有问题生成服务复盘并安排客服跟进。",
        "delivery_confirm": "发送交付清单和培训时间，确认上线责任人。",
        "contract_close": "发送合同/付款确认信息，推动进入签约。",
        "quote_follow_up": "发送报价补充材料，约定下一次演示或合同沟通。",
        "demo_invite": "确认需求、预算和演示时间，推进到报价。",
    }
    objection_handlers = [
        "客户没时间：先压缩为 30 秒确认诉求，并约下一次沟通时间。",
        "客户嫌贵：先复述预算压力，再给出套餐差异和首月优惠边界。",
        "客户要人工：立即标记人工跟进，并把通话纪要同步给负责人。",
    ]
    return {
        "opening": openings.get(purpose, openings["demo_invite"]),
        "context": memory or f"客户当前阶段：{stage_label}",
        "key_points": [
            f"当前阶段：{stage_label}",
            f"主动任务：{active_task}",
            "确认客户下一步动作、时间和责任人。",
        ],
        "objection_handlers": objection_handlers,
        "close_next_action": close_actions.get(purpose, close_actions["demo_invite"]),
    }


def list_outbound_calls(customer_id: int | None = None) -> list[dict[str, Any]]:
    calls = [item for item in _read_disk().get("calls", []) if isinstance(item, dict)]
    if customer_id is not None and int(customer_id) > 0:
        uid = int(customer_id)
        calls = [item for item in calls if int(item.get("customer_id") or 0) == uid]
    return sorted(calls, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)


def plan_outbound_call(
    customer_id: int,
    *,
    purpose: str = "follow_up",
    assignee: str = "AI外呼助手",
    actor: str = "system",
) -> dict[str, Any]:
    uid = int(customer_id)
    if uid <= 0:
        raise ValueError("customer_id 无效")

    context = customer_message_context(uid)
    insight = customer_agent_operating_insight(uid)
    ticket_summary = service_ticket_summary(uid)
    stage = normalize_stage_id(str(context.get("stage") or "idle"))
    resolved_purpose = _purpose_from_stage(stage, purpose)
    script = _script_for_call(context, insight, resolved_purpose)
    doc = load_pipeline(uid)
    call = {
        "id": f"call_{secrets.token_hex(6)}",
        "customer_id": uid,
        "customer_name": context.get("customer_name") or f"客户{uid}",
        "purpose": resolved_purpose,
        "status": "planned",
        "assignee": str(assignee or "AI外呼助手")[:80],
        "actor": str(actor or "system")[:80],
        "phone": str(doc.get("phone") or ""),
        "stage": stage,
        "stage_label": context.get("stage_label") or _stage_label(stage),
        "ai_score": context.get("ai_score") or 0,
        "pending_ticket_id": str((ticket_summary.get("latest") or {}).get("id") or ""),
        "script": script,
        "transcript": [],
        "outcome": "",
        "outcome_label": "",
        "summary": "",
        "next_action": script["close_next_action"],
        "duration_sec": 0,
        "message_ids": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    data = _read_disk()
    calls = [item for item in data.get("calls", []) if isinstance(item, dict)]
    calls.append(call)
    data["calls"] = calls
    _write_disk(data)
    return call


def _outcome_plan(outcome: str, call: dict[str, Any]) -> dict[str, Any]:
    value = str(outcome or "").strip() or "demo_booked"
    stage = normalize_stage_id(str(call.get("stage") or "idle"))
    if value == "payment_confirmed":
        return {
            "outcome": value,
            "label": "客户确认付款",
            "target_stage": "signed",
            "customer_line": "合同和付款我确认了，麻烦发交付清单并安排上线。",
            "summary": "客户在电话中确认付款，要求安排交付。",
            "next_action": "发送交付清单，安排上线培训和责任人。",
            "intent": "成交确认",
        }
    if value == "contract_confirmed":
        return {
            "outcome": value,
            "label": "合同意向明确",
            "target_stage": "contract_pending",
            "customer_line": "方案可以，合同发我看一下，没问题今天确认。",
            "summary": "客户确认方案可接受，要求发送合同。",
            "next_action": "发送合同和付款信息，确认签约节点。",
            "intent": "签约推进",
        }
    if value == "delivered_feedback":
        return {
            "outcome": value,
            "label": "交付回访完成",
            "target_stage": "delivered",
            "customer_line": "目前已经上线，整体满意，有问题我再反馈。",
            "summary": "客户确认已上线并给出满意反馈。",
            "next_action": "记录满意度，7 天后回访复购或转介绍。",
            "intent": "交付回访",
        }
    if value == "not_interested":
        return {
            "outcome": value,
            "label": "暂不考虑",
            "target_stage": stage,
            "customer_line": "暂时先不考虑，后面有需要再联系。",
            "summary": "客户暂不考虑购买，保留轻量跟进。",
            "next_action": "7 天后轻量触达，不再高频打扰。",
            "intent": "低意向",
        }
    if value == "unreachable":
        return {
            "outcome": value,
            "label": "未接通",
            "target_stage": stage,
            "customer_line": "电话未接通。",
            "summary": "本次外呼未接通，需改用短信/企微补充触达。",
            "next_action": "发送短信或企微提醒，并设置下次外呼时间。",
            "intent": "待跟进",
        }
    return {
        "outcome": "demo_booked",
        "label": "已约演示",
        "target_stage": "quoted",
        "customer_line": "可以，我愿意看演示，也麻烦把方案和报价发我。",
        "summary": "客户接受电话跟进并约定演示，需要发送方案和报价。",
        "next_action": "发送报价方案，按约定时间完成演示。",
        "intent": "演示邀约",
    }


def _save_call_message(
    *,
    call: dict[str, Any],
    direction: str,
    content: str,
    turn: int,
    outcome: str,
) -> str:
    uid = int(call.get("customer_id") or 0)
    message_id = f"outbound-call:{call.get('id')}:{turn}:{direction}:{secrets.token_hex(3)}"
    msg = UnifiedMessage(
        id=message_id,
        customer_id=uid,
        channel_type="phone",
        contact_id=f"phone:{uid}",
        contact_name=str(call.get("customer_name") or f"客户{uid}"),
        direction=direction,
        content=content,
        content_type="text",
        metadata={
            "source": "outbound_call",
            "call_id": str(call.get("id") or ""),
            "outcome": outcome,
            "turn": turn,
        },
        created_at=_now_iso(),
    )
    saved = save_message(msg)
    return str(saved.id)


def _sync_pipeline_after_call(call: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    uid = int(call.get("customer_id") or 0)
    doc = load_pipeline(uid)
    target_stage = normalize_stage_id(str(plan.get("target_stage") or doc.get("stage") or "idle"))
    if _stage_rank(target_stage) > _stage_rank(str(doc.get("stage") or "idle")):
        doc = set_pipeline_stage(
            uid,
            target_stage,
            source="outbound_call",
            note=str(plan.get("label") or "AI 外呼推进"),
        )
    doc = load_pipeline(uid)
    sources = [str(item) for item in (doc.get("channel_sources") or []) if str(item).strip()]
    if "phone" not in sources:
        sources.append("phone")
    tags = [str(item) for item in (doc.get("tags") or []) if str(item).strip()]
    for tag in ("AI外呼", str(plan.get("label") or "")):
        if tag and tag not in tags:
            tags.append(tag)
    doc["channel_sources"] = sources
    doc["tags"] = tags[:20]
    doc["last_outbound_call_id"] = str(call.get("id") or "")
    doc["last_outbound_call_status"] = "completed"
    doc["last_outbound_call_outcome"] = str(plan.get("outcome") or "")
    doc["last_outbound_call_at"] = _now_iso()
    doc["pending_follow_up"] = str(plan.get("outcome") or "") not in {"not_interested", "unreachable"}
    doc["next_action"] = str(plan.get("next_action") or doc.get("next_action") or "")
    return save_pipeline(doc)


def execute_outbound_call(call_id: str, *, outcome: str = "demo_booked", note: str = "", actor: str = "system") -> dict[str, Any]:
    data = _read_disk()
    calls = [item for item in data.get("calls", []) if isinstance(item, dict)]
    index = _call_index(calls, call_id)
    call = dict(calls[index])
    if str(call.get("status") or "") == "completed":
        return call

    plan = _outcome_plan(outcome, call)
    opening = str((call.get("script") or {}).get("opening") or "您好，我是客来来 AI 外呼助手。")
    close_action = str(plan.get("next_action") or "")
    transcript = [
        {"role": "agent", "content": opening, "at": _now_iso()},
        {"role": "customer", "content": str(plan.get("customer_line") or ""), "at": _now_iso()},
        {"role": "agent", "content": f"收到，我会{close_action}", "at": _now_iso()},
    ]
    if note.strip():
        transcript.append({"role": "agent", "content": f"备注：{note.strip()[:300]}", "at": _now_iso()})

    message_ids: list[str] = []
    message_ids.append(
        _save_call_message(
            call=call,
            direction="outbound",
            content=f"【AI外呼】{opening}",
            turn=1,
            outcome=str(plan.get("outcome") or ""),
        )
    )
    message_ids.append(
        _save_call_message(
            call=call,
            direction="inbound",
            content=f"【电话纪要】{plan.get('customer_line')} 下一步：{plan.get('next_action')}",
            turn=2,
            outcome=str(plan.get("outcome") or ""),
        )
    )

    pipeline_doc = _sync_pipeline_after_call(call, plan)
    call.update(
        {
            "status": "completed",
            "actor": str(actor or call.get("actor") or "system")[:80],
            "outcome": plan.get("outcome"),
            "outcome_label": plan.get("label"),
            "intent": plan.get("intent"),
            "summary": plan.get("summary"),
            "next_action": plan.get("next_action"),
            "duration_sec": 82 if str(plan.get("outcome") or "") != "unreachable" else 18,
            "transcript": transcript,
            "message_ids": message_ids,
            "pipeline_stage": pipeline_doc.get("stage"),
            "pipeline_stage_label": _stage_label(str(pipeline_doc.get("stage") or "")),
            "executed_at": _now_iso(),
            "updated_at": _now_iso(),
        }
    )
    calls[index] = call
    data["calls"] = calls
    _write_disk(data)
    return call


def outbound_call_summary(customer_id: int) -> dict[str, Any]:
    uid = int(customer_id)
    calls = list_outbound_calls(uid)
    completed = [item for item in calls if str(item.get("status") or "") == "completed"]
    planned = [item for item in calls if str(item.get("status") or "") != "completed"]
    phone_messages = get_messages(uid, channel_type="phone", limit=50)
    return {
        "customer_id": uid,
        "total": len(calls),
        "planned": len(planned),
        "completed": len(completed),
        "latest": calls[0] if calls else None,
        "calls": calls[:20],
        "phone_message_count": len(phone_messages),
    }


__all__ = [
    "execute_outbound_call",
    "list_outbound_calls",
    "outbound_call_summary",
    "plan_outbound_call",
]
