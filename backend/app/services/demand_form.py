"""客来来需求表单：落地页链接、webhook 与 pipeline 同步。"""

from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _landing_base_url(base_url: str = "") -> str:
    raw = (base_url or os.environ.get("KELLAI_LANDING_BASE_URL") or "").strip()
    if not raw:
        raw = "http://127.0.0.1:8080"
    return raw.rstrip("/")


def build_intake_form_url(
    customer_id: int,
    *,
    brief: str = "",
    client_name: str = "",
    base_url: str = "",
) -> str:
    base = _landing_base_url(base_url)
    params: dict[str, str] = {"customer_id": str(int(customer_id))}
    if client_name.strip():
        params["client"] = client_name.strip()[:128]
    if brief.strip():
        params["brief"] = brief.strip()[:500]
    return f"{base}/contact?{urlencode(params)}"


def verify_webhook_secret(header: str | None) -> bool:
    expected = (os.environ.get("KELLAI_INTAKE_WEBHOOK_SECRET") or "").strip()
    if not expected:
        return True
    got = (header or "").strip()
    return hmac.compare_digest(got, expected)


def _resolve_customer_id(payload: dict[str, Any]) -> int:
    raw = payload.get("customer_id") or payload.get("market_user_id") or 0
    return int(raw)


def apply_landing_submission_to_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.pipeline import load_pipeline, save_pipeline, set_pipeline_stage

    uid = _resolve_customer_id(payload)
    if uid <= 0:
        raise ValueError("customer_id 无效")
    doc = load_pipeline(uid, username=str(payload.get("username") or ""))
    intake = {
        "name": str(payload.get("name") or "").strip(),
        "email": str(payload.get("email") or "").strip(),
        "phone": str(payload.get("phone") or "").strip(),
        "company": str(payload.get("company") or "").strip(),
        "message": str(payload.get("message") or "").strip(),
        "desktop_os": str(payload.get("desktop_os") or "").strip(),
        "need_mobile": bool(payload.get("need_mobile", True)),
    }
    doc["intake_form"] = intake
    if intake.get("company"):
        doc["erp_customer_name"] = intake["company"]
    submitted = str(payload.get("submitted_at") or _now_iso())
    doc["intake_submitted_at"] = submitted
    if int(payload.get("landing_contact_id") or 0) > 0:
        doc["landing_contact_id"] = int(payload["landing_contact_id"])
    doc = set_pipeline_stage(uid, "intake_done", username=doc.get("username") or "", source="landing")
    return save_pipeline(doc)


async def fetch_submission_by_audit_code(audit_code: str) -> dict[str, Any]:
    code = str(audit_code or "").strip()
    if len(code) < 4:
        raise ValueError("审核码格式无效")
    return {
        "audit_code": code,
        "name": "",
        "company": "",
        "message": "",
        "submitted_at": "",
        "source": "local_stub",
    }


async def redeem_submission_by_audit_code(
    customer_id: int,
    audit_code: str,
    *,
    username: str = "",
) -> dict[str, Any]:
    submission = await fetch_submission_by_audit_code(audit_code)
    payload = {
        "customer_id": int(customer_id),
        "username": username,
        "name": submission.get("name") or "",
        "company": submission.get("company") or "",
        "message": submission.get("message") or "",
        "submitted_at": submission.get("submitted_at") or _now_iso(),
        "audit_code": audit_code,
    }
    return apply_landing_submission_to_pipeline(payload)


async def sync_intake_from_remote_if_newer(
    customer_id: int,
    *,
    username: str = "",
) -> dict[str, Any] | None:
    base = (os.environ.get("KELLAI_REMOTE_INTAKE_URL") or "").strip().rstrip("/")
    if not base:
        return None
    try:
        import httpx

        resp = httpx.get(
            f"{base}/api/intake-status",
            params={"customer_id": int(customer_id)},
            timeout=8.0,
            trust_env=False,
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        if not isinstance(data, dict) or not data.get("submitted_at"):
            return None
        payload = {
            "customer_id": int(customer_id),
            "username": username,
            **{
                k: data.get(k)
                for k in ("name", "email", "phone", "company", "message", "submitted_at", "landing_contact_id")
            },
        }
        return apply_landing_submission_to_pipeline(payload)
    except Exception:
        logger.debug("sync_intake_from_remote_if_newer skipped", exc_info=True)
        return None
