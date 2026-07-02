"""Human handoff and service ticket loop for high-risk conversations."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services.quality_inspection import inspect_customer_conversation


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _data_root() -> Path:
    from app.services.llm_config import _data_root as llm_data_root

    return llm_data_root()


def _ticket_path() -> Path:
    return _data_root() / "service_tickets.json"


def _read_disk() -> dict[str, Any]:
    path = _ticket_path()
    if not path.is_file():
        return {"tickets": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"tickets": []}
    if not isinstance(data, dict):
        return {"tickets": []}
    if not isinstance(data.get("tickets"), list):
        data["tickets"] = []
    return data


def _write_disk(data: dict[str, Any]) -> dict[str, Any]:
    path = _ticket_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def _event(action: str, *, actor: str = "system", note: str = "") -> dict[str, Any]:
    return {
        "action": action,
        "actor": str(actor or "system")[:80],
        "note": str(note or "")[:500],
        "at": _now_iso(),
    }


def _ticket_index(tickets: list[dict[str, Any]], ticket_id: str) -> int:
    for index, item in enumerate(tickets):
        if str(item.get("id") or "") == str(ticket_id):
            return index
    raise ValueError(f"未找到工单: {ticket_id}")


def list_service_tickets(customer_id: int | None = None, *, include_resolved: bool = True) -> list[dict[str, Any]]:
    tickets = [item for item in _read_disk().get("tickets", []) if isinstance(item, dict)]
    if customer_id is not None and int(customer_id) > 0:
        uid = int(customer_id)
        tickets = [item for item in tickets if int(item.get("customer_id") or 0) == uid]
    if not include_resolved:
        tickets = [item for item in tickets if str(item.get("status") or "") != "resolved"]
    return sorted(tickets, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)


def create_service_ticket(payload: dict[str, Any]) -> dict[str, Any]:
    data = _read_disk()
    tickets = [item for item in data.get("tickets", []) if isinstance(item, dict)]
    customer_id = int(payload.get("customer_id") or 0)
    if customer_id <= 0:
        raise ValueError("customer_id 无效")

    sla_minutes = int(payload.get("sla_minutes") or 30)
    due_at = (_now() + timedelta(minutes=max(5, min(sla_minutes, 24 * 60)))).isoformat()
    rules = payload.get("risk_rules") if isinstance(payload.get("risk_rules"), list) else []
    recommendations = payload.get("recommendations") if isinstance(payload.get("recommendations"), list) else []
    ticket = {
        "id": str(payload.get("id") or f"ticket_{secrets.token_hex(6)}"),
        "customer_id": customer_id,
        "title": str(payload.get("title") or "高风险会话转人工")[:160],
        "source": str(payload.get("source") or "quality_inspection")[:80],
        "status": "open",
        "priority": str(payload.get("priority") or "high")[:32],
        "risk_level": str(payload.get("risk_level") or "high")[:32],
        "assignee": str(payload.get("assignee") or "")[:80],
        "reason": str(payload.get("reason") or "")[:1000],
        "risk_rules": rules[:10],
        "recommendations": [str(item)[:500] for item in recommendations[:8]],
        "sla_minutes": max(5, min(sla_minutes, 24 * 60)),
        "due_at": due_at,
        "resolved_at": "",
        "resolution": "",
        "ai_rehost_action": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "events": [_event("created", note=str(payload.get("reason") or ""))],
    }
    tickets.append(ticket)
    data["tickets"] = tickets
    _write_disk(data)
    return ticket


def create_ticket_from_quality(customer_id: int, *, assignee: str = "", sla_minutes: int = 30) -> dict[str, Any]:
    report = inspect_customer_conversation(int(customer_id))
    rules = report.get("failed_rules") if isinstance(report.get("failed_rules"), list) else []
    if not report.get("review_required"):
        raise ValueError("当前客户无需转人工工单")
    title = "主管介入：客服质检高风险"
    reason = str((report.get("manager_report") or {}).get("summary") or "客服质检要求主管复核")
    priority = "urgent" if str(report.get("risk_level") or "") == "high" else "normal"
    return create_service_ticket(
        {
            "customer_id": int(customer_id),
            "title": title,
            "source": "quality_inspection",
            "priority": priority,
            "risk_level": report.get("risk_level") or "high",
            "assignee": assignee,
            "reason": reason,
            "risk_rules": rules,
            "recommendations": report.get("recommendations") or [],
            "sla_minutes": sla_minutes,
        }
    )


def assign_service_ticket(ticket_id: str, assignee: str, *, actor: str = "system") -> dict[str, Any]:
    data = _read_disk()
    tickets = [item for item in data.get("tickets", []) if isinstance(item, dict)]
    index = _ticket_index(tickets, ticket_id)
    ticket = dict(tickets[index])
    ticket["assignee"] = str(assignee or "主管")[:80]
    ticket["status"] = "assigned"
    ticket["updated_at"] = _now_iso()
    events = [item for item in ticket.get("events", []) if isinstance(item, dict)]
    events.append(_event("assigned", actor=actor, note=f"指派给 {ticket['assignee']}"))
    ticket["events"] = events
    tickets[index] = ticket
    data["tickets"] = tickets
    _write_disk(data)
    return ticket


def resolve_service_ticket(
    ticket_id: str,
    resolution: str,
    *,
    actor: str = "system",
    rehost_to_ai: bool = True,
) -> dict[str, Any]:
    data = _read_disk()
    tickets = [item for item in data.get("tickets", []) if isinstance(item, dict)]
    index = _ticket_index(tickets, ticket_id)
    ticket = dict(tickets[index])
    ticket["status"] = "resolved"
    ticket["resolution"] = str(resolution or "已处理并同步客户")[:1000]
    ticket["resolved_at"] = _now_iso()
    ticket["updated_at"] = ticket["resolved_at"]
    if rehost_to_ai:
        ticket["ai_rehost_action"] = "主管已处理高风险会话，AI 可继续按合规话术跟进客户下一步。"
    events = [item for item in ticket.get("events", []) if isinstance(item, dict)]
    events.append(_event("resolved", actor=actor, note=ticket["resolution"]))
    if rehost_to_ai:
        events.append(_event("rehosted_to_ai", actor=actor, note=ticket["ai_rehost_action"]))
    ticket["events"] = events
    tickets[index] = ticket
    data["tickets"] = tickets
    _write_disk(data)

    try:
        from app.services.pipeline import load_pipeline, save_pipeline

        doc = load_pipeline(int(ticket.get("customer_id") or 0))
        doc["pending_human_handoff"] = False
        doc["last_service_ticket_id"] = ticket["id"]
        doc["last_service_ticket_status"] = "resolved"
        doc["next_action"] = ticket["ai_rehost_action"] or doc.get("next_action") or ""
        save_pipeline(doc)
    except Exception:
        pass

    return ticket


def service_ticket_summary(customer_id: int) -> dict[str, Any]:
    tickets = list_service_tickets(int(customer_id))
    open_tickets = [item for item in tickets if str(item.get("status") or "") != "resolved"]
    latest = tickets[0] if tickets else None
    return {
        "customer_id": int(customer_id),
        "total": len(tickets),
        "open": len(open_tickets),
        "resolved": len(tickets) - len(open_tickets),
        "latest": latest,
        "tickets": tickets[:20],
    }


__all__ = [
    "assign_service_ticket",
    "create_service_ticket",
    "create_ticket_from_quality",
    "list_service_tickets",
    "resolve_service_ticket",
    "service_ticket_summary",
]
