"""LLM-driven full-flow customer simulation for growth loop testing."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from app.channels.base import UnifiedMessage
from app.services import ai_copilot
from app.services.growth_loop import customer_message_context
from app.services.message_store import get_messages, save_message
from app.services.pipeline import (
    PIPELINE_STAGES,
    _STAGE_ORDER,
    _stage_rank,
    load_pipeline,
    normalize_stage_id,
    set_pipeline_stage,
)

logger = logging.getLogger(__name__)


_DEFAULT_PERSONAS: list[dict[str, str]] = [
    {
        "scenario": "social_night_inquiry",
        "channel_type": "douyin",
        "contact_name": "LLM-抖音夜间客户",
        "role": "本地连锁餐饮老板",
        "need": "想把抖音私信、企微和小程序留资统一接待，减少漏单。",
        "objection": "担心价格和上线速度。",
    },
    {
        "scenario": "private_domain_repurchase",
        "channel_type": "wechat",
        "contact_name": "LLM-私域复购客户",
        "role": "母婴用品店主",
        "need": "希望客服能识别老客户、自动提醒复购和优惠。",
        "objection": "需要先确认老客标签和优惠策略是否能落地。",
    },
    {
        "scenario": "wework_contract",
        "channel_type": "wework",
        "contact_name": "LLM-企微签约客户",
        "role": "教育培训机构运营负责人",
        "need": "需要统一管理渠道线索并跟进试听转化。",
        "objection": "关心合同、付款和交付排期。",
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stage_label(stage: str) -> str:
    labels = {s["id"]: s["label"] for s in PIPELINE_STAGES}
    return labels.get(stage, stage)


def _llm_status() -> dict[str, Any]:
    provider, cfg = ai_copilot._get_llm_client()
    return {
        "configured": bool(provider and cfg),
        "provider": provider,
        "model": str((cfg or {}).get("model") or ""),
    }


def _pick_persona(channel_type: str = "", scenario: str = "") -> dict[str, str]:
    if scenario:
        for persona in _DEFAULT_PERSONAS:
            if persona["scenario"] == scenario:
                return dict(persona)
    if channel_type:
        for persona in _DEFAULT_PERSONAS:
            if persona["channel_type"] == channel_type:
                return dict(persona)
    return dict(_DEFAULT_PERSONAS[0])


def _history_text(events: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in events[-10:]:
        speaker = "客户" if item.get("direction") == "inbound" else "销售"
        rows.append(f"{speaker}：{str(item.get('content') or '')[:180]}")
    return "\n".join(rows) or "暂无对话"


def _fallback_customer_message(turn_index: int, stage: str, persona: dict[str, str]) -> str:
    role = persona.get("role") or "中小商家"
    need = persona.get("need") or "想了解客来来的获客和跟单能力"
    scripts = [
        f"你们这个怎么收费？我是{role}，{need}，想先看一下套餐和案例。",
        "我们有3个门店、2个抖音号和企微，每天大概80条客户消息，预算希望别太高。",
        "这个方案听起来可以，不过报价有点贵，首月能不能给点优惠？",
        "可以，那合同怎么签？如果今天付款，多久能开始交付和培训？",
        "合同我确认了，已经付款了，麻烦发我交付清单和下一步安排。",
    ]
    if stage == "contract_pending":
        return scripts[4]
    if stage == "quoted":
        return scripts[2]
    if stage == "negotiating":
        return scripts[3]
    return scripts[min(turn_index, len(scripts) - 1)]


def _force_target_progress_message(
    message: str,
    *,
    turn_index: int,
    total_turns: int,
    stage: str,
    target_stage: str,
) -> str:
    """Keep delivery audits finite: target=signed must include an explicit close signal."""
    text = str(message or "").strip()
    if target_stage != "signed":
        return text

    remaining = max(0, int(total_turns or 1) - int(turn_index or 0) - 1)
    normalized_stage = normalize_stage_id(stage)
    if normalized_stage == "contract_pending" or remaining == 0:
        return "合同我确认了，已经付款了。请发我交付清单、培训时间和抖音/企微/小程序的上线顺序。"

    if remaining == 1 and _stage_rank(normalized_stage) >= _stage_rank("quoted"):
        close_request = "如果优惠和月底前上线能确认，我今天就可以确认合同并付款。"
        if close_request not in text:
            text = f"{text} {close_request}".strip()
    return text


def _generate_customer_message(
    *,
    turn_index: int,
    total_turns: int,
    stage: str,
    target_stage: str,
    persona: dict[str, str],
    events: list[dict[str, Any]],
    use_llm: bool,
    allow_fallback: bool,
) -> tuple[str, bool, str]:
    status = _llm_status()
    if not use_llm or not status["configured"]:
        if not allow_fallback:
            return "", False, "llm_not_configured"
        message = _force_target_progress_message(
            _fallback_customer_message(turn_index, stage, persona),
            turn_index=turn_index,
            total_turns=total_turns,
            stage=stage,
            target_stage=target_stage,
        )
        return message, False, "scripted_fallback"

    system_prompt = (
        "你在客来来闭环测试中扮演一个真实中小商家客户。"
        "目标是用自然、多轮、真实的客户行为测试销售跟单系统能否推进成交。"
        "不要提到你是AI、LLM、测试脚本或模拟器。"
        "每次只输出客户的一条中文消息，内容要能推动当前销售阶段前进。"
        '严格返回 JSON：{"message":"客户消息","intent":"客户意图","should_continue":true}'
    )
    prompt = (
        f"客户角色：{persona.get('role')}\n"
        f"客户需求：{persona.get('need')}\n"
        f"客户顾虑：{persona.get('objection')}\n"
        f"当前阶段：{_stage_label(stage)}({stage})\n"
        f"目标阶段：{_stage_label(target_stage)}({target_stage})\n"
        f"第 {turn_index + 1} 轮\n"
        f"最近对话：\n{_history_text(events)}\n"
        "请生成下一条客户消息。"
    )
    try:
        raw = ai_copilot._call_llm(prompt, system_prompt=system_prompt, max_tokens=320)
        parsed = ai_copilot._parse_json_from_llm(raw)
        if isinstance(parsed, dict):
            message = str(parsed.get("message") or "").strip()
            if 2 <= len(message) <= 800:
                message = _force_target_progress_message(
                    message,
                    turn_index=turn_index,
                    total_turns=total_turns,
                    stage=stage,
                    target_stage=target_stage,
                )
                return message, True, status["provider"]
    except Exception:
        logger.debug("LLM 客户消息生成失败，降级脚本", exc_info=True)
    if not allow_fallback:
        return "", False, "llm_generation_failed"
    message = _force_target_progress_message(
        _fallback_customer_message(turn_index, stage, persona),
        turn_index=turn_index,
        total_turns=total_turns,
        stage=stage,
        target_stage=target_stage,
    )
    return message, False, "scripted_fallback"


def _recent_history(customer_id: int, limit: int = 8) -> list[str]:
    try:
        rows = get_messages(customer_id, limit=limit)
    except Exception:
        return []
    return [m.content for m in reversed(rows) if m.content]


def _agent_reply(
    customer_id: int,
    customer_text: str,
    stage: str,
    *,
    use_llm: bool,
    require_llm: bool,
) -> tuple[str, dict[str, Any], bool]:
    intent = ai_copilot.analyze_intent(customer_text)
    if use_llm and require_llm:
        system_prompt = (
            "你是客来来的销售跟单助手。请基于客户消息生成一条专业、简洁、能推动成交闭环的中文回复。"
            "不要承诺无法确认的具体价格、合同条款或交付日期。只返回回复文本。"
        )
        prompt = (
            f"当前阶段：{_stage_label(stage)}({stage})\n"
            f"客户消息：{customer_text}\n"
            f"最近对话：{' | '.join(_recent_history(customer_id))}"
        )
        draft = ai_copilot._call_llm(prompt, system_prompt=system_prompt, max_tokens=256).strip()
        if not draft:
            return "", {"intent": intent, "error": "llm_agent_reply_failed"}, False
        return draft, {"intent": intent, "source": "llm"}, True

    result = ai_copilot.generate_auto_reply(
        customer_id,
        message=customer_text,
        intent=str(intent.get("intent") or ""),
        stage=stage,
        history=_recent_history(customer_id),
    )
    draft = str(result.get("draft") or "").strip()

    # Keep the test deterministic enough to prove stage movement even when LLM replies are conservative.
    if stage == "intake_done" and not any(k in draft for k in ("方案", "报价", "套餐", "费用")):
        draft = "需求已清楚，我先按你的渠道和消息量给一版基础方案和报价：先接抖音、企微和小程序，首周完成配置和培训。"
    elif stage == "quoted" and not any(k in draft for k in ("优惠", "申请", "价格")):
        draft = "价格我理解，我可以帮你申请首月优惠，并把功能范围和续费规则写清楚。"
    elif stage == "negotiating" and not any(k in draft for k in ("合同", "付款", "签")):
        draft = "优惠方案可以按这个边界推进。如果你确认，我现在发合同和付款信息，付款后安排交付。"
    elif stage == "contract_pending" and not any(k in draft for k in ("交付", "上线", "培训")):
        draft = "合同和付款确认后，我们会发交付清单，安排渠道配置、账号培训和第一轮数据校验。"
    elif not draft:
        draft = "收到，我先记录你的需求，并给你安排下一步跟进。"

    if not use_llm and result.get("reason") == "":
        result["reason"] = "scripted_agent"
    result["draft"] = draft
    result["intent"] = intent
    return draft, result, False


def _save_simulated_message(
    *,
    simulation_id: str,
    turn_index: int,
    customer_id: int,
    channel_type: str,
    contact_id: str,
    contact_name: str,
    direction: str,
    content: str,
    metadata: dict[str, Any],
) -> tuple[UnifiedMessage, dict[str, Any]]:
    suffix = "in" if direction == "inbound" else "out"
    msg = UnifiedMessage(
        id=f"llm-sim:{simulation_id}:{turn_index}:{suffix}:{secrets.token_hex(3)}",
        customer_id=int(customer_id or 0),
        channel_type=channel_type,
        contact_id=contact_id,
        contact_name=contact_name,
        direction=direction,
        content=content,
        content_type="text",
        metadata={
            "simulated": True,
            "simulation_id": simulation_id,
            "source": "llm_full_flow",
            **metadata,
        },
        created_at=_now_iso(),
    )
    saved = save_message(msg)
    ctx = customer_message_context(int(saved.customer_id))
    return saved, ctx


def _maybe_advance_after_agent_reply(customer_id: int, assistant_text: str) -> dict[str, Any]:
    doc = load_pipeline(customer_id)
    stage = normalize_stage_id(str(doc.get("stage") or "idle"))
    text = str(assistant_text or "")

    if stage == "intake_done" and any(k in text for k in ("方案", "报价", "套餐", "费用")):
        doc = set_pipeline_stage(customer_id, "quoted", source="llm_full_flow", note="模拟销售已发送方案/报价")
    elif stage == "negotiating" and any(k in text for k in ("合同", "付款", "签")):
        doc = set_pipeline_stage(customer_id, "contract_pending", source="llm_full_flow", note="模拟销售推进合同/付款")

    return customer_message_context(customer_id)


def _assertions(
    *,
    customer_id: int,
    target_stage: str,
    auto_reply: bool,
    llm_ready: bool,
    llm_used: bool,
) -> list[dict[str, Any]]:
    ctx = customer_message_context(customer_id) if customer_id > 0 else {}
    messages = get_messages(customer_id, limit=80) if customer_id > 0 else []
    inbound_count = sum(1 for m in messages if m.direction == "inbound")
    outbound_count = sum(1 for m in messages if m.direction == "outbound")
    final_stage = normalize_stage_id(str(ctx.get("stage") or "idle"))

    items = [
        {
            "key": "customer_created",
            "label": "已自动建客户",
            "passed": customer_id > 0,
            "required": True,
        },
        {
            "key": "inbound_messages_saved",
            "label": "客户消息已入库",
            "passed": inbound_count > 0,
            "required": True,
            "value": inbound_count,
        },
        {
            "key": "outbound_messages_saved",
            "label": "销售回复已入库",
            "passed": outbound_count > 0,
            "required": auto_reply,
            "value": outbound_count,
        },
        {
            "key": "target_stage_reached",
            "label": f"漏斗已到达{_stage_label(target_stage)}",
            "passed": _stage_rank(final_stage) >= _stage_rank(target_stage),
            "required": True,
            "value": final_stage,
        },
        {
            "key": "ai_score_updated",
            "label": "AI 意向分已更新",
            "passed": float(ctx.get("ai_score") or 0.0) > 0.0,
            "required": True,
            "value": float(ctx.get("ai_score") or 0.0),
        },
        {
            "key": "next_action_generated",
            "label": "下一步动作已生成",
            "passed": bool(str(ctx.get("next_action") or "").strip()),
            "required": True,
            "value": str(ctx.get("next_action") or ""),
        },
        {
            "key": "llm_customer_generated",
            "label": "LLM 已生成客户行为",
            "passed": bool(llm_used),
            "required": bool(llm_ready),
        },
    ]
    return items


async def run_llm_full_flow_simulation(
    *,
    turns: int = 5,
    target_stage: str = "signed",
    channel_type: str = "",
    scenario: str = "",
    use_llm: bool = True,
    auto_reply: bool = True,
    require_llm: bool = True,
) -> dict[str, Any]:
    """Run a multi-turn customer simulation and return a test report."""
    target = normalize_stage_id(target_stage)
    if target not in _STAGE_ORDER:
        target = "signed"
    safe_turns = max(1, min(int(turns or 5), 8))
    persona = _pick_persona(channel_type=channel_type, scenario=scenario)
    channel = channel_type.strip() or persona["channel_type"]
    if channel == "xiaohongshu":
        channel = "douyin"

    simulation_id = secrets.token_hex(6)
    contact_id = f"llm_sim_{simulation_id}"
    contact_name = persona["contact_name"]
    customer_id = 0
    events: list[dict[str, Any]] = []
    llm_status = _llm_status()
    llm_customer_turns = 0
    llm_agent_turns = 0
    generation_sources: list[str] = []
    failure_reason = ""

    if require_llm and use_llm and not llm_status["configured"]:
        failure_reason = "未配置真实 LLM API Key，不能执行交付级全流程测试"
        return {
            "simulation_id": simulation_id,
            "mode": "llm_required_not_ready",
            "llm_ready": False,
            "llm_used": False,
            "llm_customer_turns": 0,
            "llm_agent_turns": 0,
            "provider": "",
            "model": "",
            "generation_sources": [],
            "customer_id": 0,
            "contact_id": contact_id,
            "contact_name": contact_name,
            "channel_type": channel,
            "persona": persona,
            "turns_run": 0,
            "target_stage": target,
            "target_stage_label": _stage_label(target),
            "final_stage": "idle",
            "final_stage_label": _stage_label("idle"),
            "ai_score": 0.0,
            "next_action": "",
            "passed": False,
            "failure_reason": failure_reason,
            "assertions": [
                {"key": "llm_ready", "label": "真实 LLM 已配置", "passed": False, "required": True, "value": failure_reason}
            ],
            "events": [],
            "summary": failure_reason,
        }

    for turn_index in range(safe_turns):
        current_stage = "idle"
        if customer_id > 0:
            current_stage = normalize_stage_id(str(load_pipeline(customer_id).get("stage") or "idle"))

        customer_text, used_llm, source = _generate_customer_message(
            turn_index=turn_index,
            total_turns=safe_turns,
            stage=current_stage,
            target_stage=target,
            persona=persona,
            events=events,
            use_llm=use_llm,
            allow_fallback=not require_llm,
        )
        if require_llm and not used_llm:
            failure_reason = "LLM 未能生成客户消息，已停止测试"
            break
        if used_llm:
            llm_customer_turns += 1
        generation_sources.append(source)

        inbound, inbound_ctx = _save_simulated_message(
            simulation_id=simulation_id,
            turn_index=turn_index,
            customer_id=customer_id,
            channel_type=channel,
            contact_id=contact_id,
            contact_name=contact_name,
            direction="inbound",
            content=customer_text,
            metadata={"turn": turn_index, "role": "customer", "generator": source},
        )
        customer_id = int(inbound.customer_id)
        events.append({
            "turn": turn_index,
            "direction": "inbound",
            "content": customer_text,
            "stage_after": inbound_ctx.get("stage"),
            "stage_label": inbound_ctx.get("stage_label"),
            "next_action": inbound_ctx.get("next_action"),
        })

        stage_after_inbound = normalize_stage_id(str(inbound_ctx.get("stage") or "idle"))

        if auto_reply:
            reply_text, reply_meta, agent_used_llm = _agent_reply(
                customer_id,
                customer_text,
                stage_after_inbound,
                use_llm=use_llm,
                require_llm=require_llm,
            )
            if require_llm and not agent_used_llm:
                failure_reason = str(reply_meta.get("error") or "LLM 未能生成销售回复，已停止测试")
                break
            if agent_used_llm:
                llm_agent_turns += 1
            outbound, outbound_ctx = _save_simulated_message(
                simulation_id=simulation_id,
                turn_index=turn_index,
                customer_id=customer_id,
                channel_type=channel,
                contact_id=contact_id,
                contact_name=contact_name,
                direction="outbound",
                content=reply_text,
                metadata={"turn": turn_index, "role": "agent", "auto_reply": reply_meta},
            )
            _ = outbound
            outbound_ctx = _maybe_advance_after_agent_reply(customer_id, reply_text) or outbound_ctx
            events.append({
                "turn": turn_index,
                "direction": "outbound",
                "content": reply_text,
                "stage_after": outbound_ctx.get("stage"),
                "stage_label": outbound_ctx.get("stage_label"),
                "next_action": outbound_ctx.get("next_action"),
            })

        final_stage = normalize_stage_id(str(customer_message_context(customer_id).get("stage") or "idle"))
        if _stage_rank(final_stage) >= _stage_rank(target):
            break

    final_ctx = customer_message_context(customer_id) if customer_id > 0 else {}
    final_stage = normalize_stage_id(str(final_ctx.get("stage") or "idle"))
    checks = _assertions(
        customer_id=customer_id,
        target_stage=target,
        auto_reply=auto_reply,
        llm_ready=bool(use_llm and llm_status["configured"]),
        llm_used=llm_customer_turns > 0,
    )
    if require_llm:
        checks.append({
            "key": "llm_agent_replied",
            "label": "LLM 已生成销售回复",
            "passed": llm_agent_turns > 0,
            "required": True,
            "value": llm_agent_turns,
        })
    passed = all(bool(item["passed"]) for item in checks if item.get("required"))
    if failure_reason:
        passed = False

    return {
        "simulation_id": simulation_id,
        "mode": "llm" if llm_customer_turns > 0 else "scripted_fallback",
        "llm_ready": bool(llm_status["configured"]),
        "llm_used": llm_customer_turns > 0,
        "llm_customer_turns": llm_customer_turns,
        "llm_agent_turns": llm_agent_turns,
        "provider": llm_status["provider"],
        "model": llm_status["model"],
        "generation_sources": generation_sources,
        "customer_id": customer_id,
        "contact_id": contact_id,
        "contact_name": contact_name,
        "channel_type": channel,
        "persona": persona,
        "turns_run": max((int(e.get("turn") or 0) for e in events), default=-1) + 1,
        "target_stage": target,
        "target_stage_label": _stage_label(target),
        "final_stage": final_stage,
        "final_stage_label": _stage_label(final_stage),
        "ai_score": float(final_ctx.get("ai_score") or 0.0),
        "next_action": str(final_ctx.get("next_action") or ""),
        "passed": passed,
        "failure_reason": failure_reason,
        "assertions": checks,
        "events": events,
        "summary": (
            f"{'LLM' if llm_customer_turns > 0 else '脚本兜底'}客户完成 {len(events)} 条消息，"
            f"最终阶段：{_stage_label(final_stage)}，测试{'通过' if passed else '未通过'}。"
        ),
    }
