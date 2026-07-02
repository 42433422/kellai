"""AI self-service resolution loop backed by knowledge base and tickets."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.channels.base import UnifiedMessage
from app.services.growth_loop import customer_message_context
from app.services.knowledge_base import suggest_answer
from app.services.message_store import get_messages, save_message
from app.services.pipeline import load_pipeline, save_pipeline
from app.services.service_tickets import create_service_ticket


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data_root() -> Path:
    from app.services.llm_config import _data_root as llm_data_root

    return llm_data_root()


def _self_service_path() -> Path:
    return _data_root() / "self_service_resolutions.json"


def _read_disk() -> dict[str, Any]:
    path = _self_service_path()
    if not path.is_file():
        return {"sessions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sessions": []}
    if not isinstance(data, dict):
        return {"sessions": []}
    if not isinstance(data.get("sessions"), list):
        data["sessions"] = []
    return data


def _write_disk(data: dict[str, Any]) -> dict[str, Any]:
    path = _self_service_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def _latest_inbound_query(customer_id: int) -> str:
    for msg in get_messages(int(customer_id), limit=30):
        if str(getattr(msg, "direction", "") or "") == "inbound":
            content = str(getattr(msg, "content", "") or "").strip()
            if content:
                return content
    ctx = customer_message_context(int(customer_id))
    return str(ctx.get("last_message_preview") or "请问客来来怎么接入和交付？").strip()


def _message_contact(customer_id: int, channel_type: str = "") -> tuple[str, str, str]:
    ctx = customer_message_context(int(customer_id))
    contacts = ctx.get("channel_contacts") if isinstance(ctx.get("channel_contacts"), dict) else {}
    chosen_channel = str(channel_type or "").strip()
    if not chosen_channel:
        sources = [str(item) for item in (ctx.get("channel_sources") or []) if str(item).strip()]
        chosen_channel = sources[0] if sources else "wework"
    contact_id = str(contacts.get(chosen_channel) or f"self_service:{customer_id}")
    contact_name = str(ctx.get("customer_name") or f"客户{customer_id}")
    return chosen_channel, contact_id, contact_name


def _save_resolution_message(
    *,
    session_id: str,
    customer_id: int,
    channel_type: str,
    contact_id: str,
    contact_name: str,
    direction: str,
    content: str,
    turn: int,
    status: str,
) -> str:
    msg = UnifiedMessage(
        id=f"self-service:{session_id}:{turn}:{direction}:{secrets.token_hex(3)}",
        customer_id=int(customer_id),
        channel_type=channel_type,
        contact_id=contact_id,
        contact_name=contact_name,
        direction=direction,
        content=content,
        content_type="text",
        metadata={
            "source": "self_service_resolution",
            "session_id": session_id,
            "status": status,
            "turn": turn,
        },
        created_at=_now_iso(),
    )
    saved = save_message(msg)
    return str(saved.id)


def _persist_session(session: dict[str, Any]) -> dict[str, Any]:
    data = _read_disk()
    sessions = [item for item in data.get("sessions", []) if isinstance(item, dict)]
    sessions = [item for item in sessions if str(item.get("id") or "") != str(session.get("id") or "")]
    sessions.append(session)
    data["sessions"] = sessions
    _write_disk(data)
    return session


def list_self_service_sessions(customer_id: int | None = None) -> list[dict[str, Any]]:
    sessions = [item for item in _read_disk().get("sessions", []) if isinstance(item, dict)]
    if customer_id is not None and int(customer_id) > 0:
        uid = int(customer_id)
        sessions = [item for item in sessions if int(item.get("customer_id") or 0) == uid]
    return sorted(sessions, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)


def run_self_service_resolution(
    customer_id: int,
    *,
    query: str = "",
    channel_type: str = "",
    fallback_to_ticket: bool = True,
    actor: str = "ai-self-service",
    persist: bool = True,
) -> dict[str, Any]:
    uid = int(customer_id)
    if uid <= 0:
        raise ValueError("customer_id 无效")

    text = str(query or "").strip() or _latest_inbound_query(uid)
    ctx = customer_message_context(uid)
    suggestion = suggest_answer(text, customer_context=ctx, limit=3)
    matched = bool(suggestion.get("matched"))
    confidence = float(suggestion.get("confidence") or 0.0)
    session_id = f"ssr_{secrets.token_hex(6)}"
    channel, contact_id, contact_name = _message_contact(uid, channel_type=channel_type)
    message_ids: list[str] = []
    ticket: dict[str, Any] | None = None

    if persist:
        message_ids.append(
            _save_resolution_message(
                session_id=session_id,
                customer_id=uid,
                channel_type=channel,
                contact_id=contact_id,
                contact_name=contact_name,
                direction="inbound",
                content=text,
                turn=1,
                status="received",
            )
        )

    if matched:
        answer = str(suggestion.get("answer") or "").strip()
        status = "resolved"
        next_action = "AI 已按知识库完成自助解答，继续观察客户是否追问。"
        if persist:
            message_ids.append(
                _save_resolution_message(
                    session_id=session_id,
                    customer_id=uid,
                    channel_type=channel,
                    contact_id=contact_id,
                    contact_name=contact_name,
                    direction="outbound",
                    content=f"【AI自助解答】{answer}",
                    turn=2,
                    status=status,
                )
            )
    else:
        answer = str(suggestion.get("answer") or "知识库暂未命中。").strip()
        status = "handoff_required"
        next_action = "AI 未命中知识库，已生成转人工工单补充答案并沉淀知识。"
        if persist and fallback_to_ticket:
            ticket = create_service_ticket(
                {
                    "customer_id": uid,
                    "title": "AI 自助未解决：转人工补充知识",
                    "source": "self_service_resolution",
                    "priority": "normal",
                    "risk_level": "medium",
                    "reason": f"客户问题未命中知识库：{text}",
                    "recommendations": [
                        "人工客服补充标准答案后沉淀到知识库。",
                        "处理后回托 AI，后续同类问题自动自助解决。",
                    ],
                    "sla_minutes": 60,
                }
            )

    if persist:
        try:
            doc = load_pipeline(uid)
            doc["last_self_service_session_id"] = session_id
            doc["last_self_service_status"] = status
            doc["last_self_service_confidence"] = confidence
            doc["next_action"] = next_action
            tags = [str(item) for item in (doc.get("tags") or []) if str(item).strip()]
            for tag in ("AI自助", "知识库命中" if matched else "转人工补知识"):
                if tag not in tags:
                    tags.append(tag)
            doc["tags"] = tags[:20]
            save_pipeline(doc)
        except Exception:
            pass

    session = {
        "id": session_id,
        "customer_id": uid,
        "customer_name": ctx.get("customer_name") or f"客户{uid}",
        "query": text,
        "channel_type": channel,
        "status": status,
        "matched": matched,
        "confidence": confidence,
        "answer": answer,
        "sources": suggestion.get("sources") or [],
        "message_ids": message_ids,
        "ticket_id": ticket.get("id") if isinstance(ticket, dict) else "",
        "ticket": ticket,
        "next_action": next_action,
        "actor": str(actor or "ai-self-service")[:80],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    return _persist_session(session) if persist else session


def self_service_summary(customer_id: int) -> dict[str, Any]:
    uid = int(customer_id)
    sessions = list_self_service_sessions(uid)
    resolved = [item for item in sessions if str(item.get("status") or "") == "resolved"]
    handoff = [item for item in sessions if str(item.get("status") or "") == "handoff_required"]
    total = len(sessions)
    return {
        "customer_id": uid,
        "total": total,
        "resolved": len(resolved),
        "handoff": len(handoff),
        "resolution_rate": round(len(resolved) / total, 4) if total else 0.0,
        "latest": sessions[0] if sessions else None,
        "sessions": sessions[:20],
    }


__all__ = [
    "list_self_service_sessions",
    "run_self_service_resolution",
    "self_service_summary",
]
