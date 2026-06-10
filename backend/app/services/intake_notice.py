"""建联欢迎语 / 需求采集话术。"""

from __future__ import annotations

import os
from typing import Any


def _product_name() -> str:
    return (os.environ.get("KELLAI_PRODUCT_NAME") or "客来来").strip() or "客来来"


def _primary_contact_name(customer_id: int) -> str:
    from app.services.pipeline import load_pipeline
    from app.services.wechat_bridge import get_bindings_for_user

    doc = load_pipeline(int(customer_id))
    intake = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}
    for key in ("company", "name"):
        val = str(intake.get(key) or "").strip()
        if val:
            return val
    erp = str(doc.get("erp_customer_name") or "").strip()
    if erp:
        return erp
    bindings = get_bindings_for_user(int(customer_id))
    if bindings:
        first = bindings[0]
        if isinstance(first, dict):
            return str(first.get("name") or first.get("contact_name") or "").strip()
    return str(doc.get("username") or "").strip()


def build_intake_form_notice_message(
    *,
    contact_name: str,
    form_url: str,
    brief: str = "",
) -> str:
    client = contact_name.strip() or "您好"
    lines = [
        f"{client}，您好！",
        f"请填写{_product_name()}需求表单，便于我们为您定制方案：",
        form_url,
        "提交后会生成审核码，请发回群内以便我们关联您的账户。",
    ]
    if brief.strip():
        lines.insert(2, f"背景：{brief.strip()[:300]}")
    return "\n".join(lines)


def maybe_send_intake_form_notice(
    customer_id: int,
    *,
    username: str = "",
    contact_name: str = "",
    brief: str = "",
    force: bool = False,
) -> dict[str, Any]:
    from app.services.demand_form import build_intake_form_url
    from app.services.pipeline import load_pipeline, save_pipeline

    uid = int(customer_id)
    doc = load_pipeline(uid, username=username)
    if doc.get("intake_form_notice_sent") and not force:
        return {"sent": False, "skipped": True, "reason": "already_sent"}
    contact = (contact_name or _primary_contact_name(uid)).strip()
    if not contact:
        return {"sent": False, "error": "未找到微信群联系人"}
    form_url = build_intake_form_url(uid, brief=brief, client_name=contact)
    text = build_intake_form_notice_message(contact_name=contact, form_url=form_url, brief=brief)
    try:
        from app.desktop_automation.service import get_desktop_automation_service

        result = get_desktop_automation_service().send_wechat_message(contact, text)
        ok = bool(result.get("success")) and bool(result.get("message_sent", result.get("success")))
    except Exception as exc:
        return {"sent": False, "error": str(exc)[:300]}
    if ok:
        doc["intake_form_notice_sent"] = True
        doc["intake_sent"] = True
        save_pipeline(doc)
    return {"sent": ok, "message": text, "form_url": form_url, "send_result": result}


def maybe_send_connected_welcome(
    customer_id: int,
    *,
    username: str = "",
    contact_name: str = "",
    force: bool = False,
) -> dict[str, Any]:
    from app.services.pipeline import load_pipeline, save_pipeline

    uid = int(customer_id)
    doc = load_pipeline(uid, username=username)
    if doc.get("connected_welcome_sent") and not force:
        return {"sent": False, "skipped": True, "reason": "already_sent"}
    contact = (contact_name or _primary_contact_name(uid)).strip()
    if not contact:
        return {"sent": False, "error": "未找到微信群联系人"}
    product = _product_name()
    text = (
        f"{contact}，您好！我是{product} AI 客服助理，已为您建立专属服务通道。\n"
        "后续需求采集、报价与交付进度都会在此群同步，请随时 @ 我。"
    )
    try:
        from app.desktop_automation.service import get_desktop_automation_service

        result = get_desktop_automation_service().send_wechat_message(contact, text)
        ok = bool(result.get("success")) and bool(result.get("message_sent", result.get("success")))
    except Exception as exc:
        return {"sent": False, "error": str(exc)[:300]}
    if ok:
        doc["connected_welcome_sent"] = True
        if str(doc.get("stage") or "idle") == "idle":
            doc["stage"] = "connected"
        save_pipeline(doc)
    return {"sent": ok, "message": text, "send_result": result}
