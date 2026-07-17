"""客来来商机 pipeline 档案（JSON 侧存储 · 自 KELLAI_DATA_DIR）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PipelineCrmGateError(Exception):
    """阶段推进被 CRM 门禁拦截。"""


PIPELINE_STAGES: list[dict[str, str]] = [
    {"id": "idle", "label": "未接触"},
    {"id": "connected", "label": "已建联"},
    {"id": "intake", "label": "需求采集"},
    {"id": "intake_done", "label": "已提交"},
    {"id": "quoted", "label": "已报价"},
    {"id": "negotiating", "label": "议价"},
    {"id": "contract_pending", "label": "待签"},
    {"id": "signed", "label": "已签"},
    {"id": "delivering", "label": "交付中"},
    {"id": "delivered", "label": "已交付"},
]

_STAGE_ORDER = [s["id"] for s in PIPELINE_STAGES]
_STAGE_LABELS = {s["id"]: s["label"] for s in PIPELINE_STAGES}
_STAGE_ALIASES: dict[str, str] = {
    "no_contact": "idle",
    "requirement": "intake",
    "submitted": "intake_done",
    "pending_sign": "contract_pending",
    "negotiation": "negotiating",
}


def normalize_stage_id(stage: str | None) -> str:
    st = str(stage or "idle").strip()
    return _STAGE_ALIASES.get(st, st)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stage_rank(stage: str | None) -> int:
    st = normalize_stage_id(stage)
    try:
        return _STAGE_ORDER.index(st)
    except ValueError:
        return 0


def _resolve_data_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        roots.append(path)

    raw = (os.environ.get("KELLAI_DATA_DIR") or "").strip()
    if raw:
        base = Path(raw).expanduser().resolve()
        add(base / "pipelines")
        add(base / "data" / "pipelines")

    repo_data = Path(__file__).resolve().parents[3] / "data" / "pipelines"
    add(repo_data)

    if not roots:
        add(Path.cwd() / "data" / "pipelines")
    return roots


def _pipeline_roots() -> list[Path]:
    roots = _resolve_data_roots()
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
    return roots


def _pipeline_file(customer_id: int) -> Path:
    uid = int(customer_id)
    if uid <= 0:
        raise ValueError("customer_id 无效")
    primary = _pipeline_roots()[0]
    return primary / f"{uid}.json"


def _default_pipeline(customer_id: int, username: str = "") -> dict[str, Any]:
    return {
        "customer_id": int(customer_id),
        "market_user_id": int(customer_id),
        "username": str(username or "").strip(),
        # 手动维护的客户资料字段
        "name": "",
        "company": "",
        "email": "",
        "phone": "",
        "note": "",
        "owner": "",
        "source": "",
        "tags": [],
        "is_demo": False,
        "created_at": _now_iso(),
        "stage": "idle",
        "channel_sources": [],
        "ai_score": 0.0,
        "ai_tags": [],
        "timeline": [],
        "intake_sent": False,
        "intake_form_notice_sent": False,
        "connected_welcome_sent": False,
        "last_message_preview": "",
        "intake_submitted_at": "",
        "landing_contact_id": 0,
        "intake_form": None,
        "erp_customer_id": 0,
        "erp_customer_name": "",
        "crm_opportunity_id": 0,
        "crm_quote_id": 0,
        "crm_funnel_synced_at": "",
        "crm_db_synced_at": "",
        "crm_invoice_id": 0,
        "updated_at": _now_iso(),
    }


def _read_pipeline_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("invalid pipeline json: %s", path)
        return None
    return raw if isinstance(raw, dict) else None


def _write_pipeline_file(path: Path, doc: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(doc)
    uid = int(doc.get("customer_id") or doc.get("market_user_id") or 0)
    if uid > 0:
        doc["customer_id"] = uid
        doc["market_user_id"] = uid
    doc["updated_at"] = _now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return doc


def _customer_id_from_doc(doc: dict[str, Any]) -> int:
    return int(doc.get("customer_id") or doc.get("market_user_id") or 0)


def load_pipeline(customer_id: int, username: str = "") -> dict[str, Any]:
    uid = int(customer_id)
    path = _pipeline_file(uid)
    doc = _read_pipeline_file(path)
    if doc is None:
        doc = _default_pipeline(uid, username=username)
        _write_pipeline_file(path, doc)
        return doc
    doc.setdefault("customer_id", uid)
    doc.setdefault("market_user_id", uid)
    if username and not doc.get("username"):
        doc["username"] = str(username).strip()
    doc["stage"] = normalize_stage_id(str(doc.get("stage") or "idle"))
    doc.setdefault("channel_sources", [])
    doc.setdefault("ai_score", 0.0)
    doc.setdefault("ai_tags", [])
    doc.setdefault("timeline", [])
    doc.setdefault("is_demo", False)
    return doc


def save_pipeline(doc: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    _ = kwargs
    uid = _customer_id_from_doc(doc)
    if uid <= 0:
        raise ValueError("pipeline 缺少 customer_id")
    path = _pipeline_file(uid)
    result = _write_pipeline_file(path, doc)
    # 双写：同步到 SQLite，失败不阻塞主流程
    try:
        from app.services.crm_store import sync_pipeline_to_sqlite
        sync_pipeline_to_sqlite(result)
    except Exception:
        logger.warning("pipeline 同步 SQLite 失败: customer_id=%s", uid, exc_info=True)
    return result


def _append_timeline(doc: dict[str, Any], stage: str, source: str, note: str = "") -> None:
    entry = {"stage": stage, "at": _now_iso(), "source": source}
    if note.strip():
        entry["note"] = note.strip()
    tl = list(doc.get("timeline") or [])
    tl.append(entry)
    doc["timeline"] = tl[-30:]


def set_pipeline_stage(
    customer_id: int,
    stage: str,
    *,
    username: str = "",
    source: str = "manual",
    note: str = "",
) -> dict[str, Any]:
    st = normalize_stage_id(stage)
    if st not in _STAGE_ORDER:
        raise ValueError(f"未知阶段: {st}")
    doc = load_pipeline(customer_id, username=username)
    if doc.get("stage") != st:
        doc["stage"] = st
        _append_timeline(doc, st, source, note=note)
    return save_pipeline(doc)


# 客户可手动维护的资料字段（用于创建/更新时白名单赋值）
_PROFILE_FIELDS = ("name", "company", "email", "phone", "note", "owner", "source")


def _display_name_from_doc(doc: dict[str, Any], username: str = "") -> str:
    # 手动维护的客户资料优先（公司 > 姓名）
    top_company = str(doc.get("company") or "").strip()
    if top_company:
        return top_company
    top_name = str(doc.get("name") or "").strip()
    if top_name:
        return top_name
    intake = doc.get("intake_form")
    if isinstance(intake, dict):
        company = str(intake.get("company") or "").strip()
        if company:
            return company
        name = str(intake.get("name") or "").strip()
        if name:
            return name
    erp = str(doc.get("erp_customer_name") or "").strip()
    if erp:
        return erp
    login = str(doc.get("username") or username or "").strip()
    return login


def _contact_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """提取客户联系信息：顶层资料优先，其次回退到需求表单。"""
    intake = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}

    def pick(*keys: str) -> str:
        for k in keys:
            v = str(doc.get(k) or "").strip()
            if v:
                return v
        for k in keys:
            v = str((intake or {}).get(k) or "").strip()
            if v:
                return v
        return ""

    return {
        "name": pick("name", "contact_name"),
        "company": pick("company", "company_name", "erp_customer_name"),
        "email": pick("email", "contact_email"),
        "phone": pick("phone", "contact_phone"),
        "owner": str(doc.get("owner") or "").strip(),
        "note": str(doc.get("note") or "").strip(),
        "source": str(doc.get("source") or "").strip(),
        "tags": list(doc.get("tags") or []),
    }


def _iter_pipeline_docs() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    seen: set[int] = set()
    for root in _pipeline_roots():
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            doc = _read_pipeline_file(path)
            if not doc:
                continue
            uid = _customer_id_from_doc(doc)
            if uid <= 0:
                try:
                    uid = int(path.stem)
                except ValueError:
                    continue
                doc["customer_id"] = uid
                doc["market_user_id"] = uid
            if uid in seen:
                continue
            seen.add(uid)
            docs.append(doc)
    return docs


def _is_demo_pipeline(doc: dict[str, Any], demo_customer_ids: set[int]) -> bool:
    uid = _customer_id_from_doc(doc)
    if bool(doc.get("is_demo")) or uid in demo_customer_ids:
        return True
    # Legacy local data created before is_demo was introduced.
    if str(doc.get("username") or "").strip().lower() == "demo":
        return True
    for entry in doc.get("timeline") or []:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("source") or "").strip().lower()
        note = str(entry.get("note") or "").strip().lower()
        if source == "test" or note.startswith("[tutorial]"):
            return True
    return False


def list_pipeline_client_summaries(*, include_demo: bool = False) -> list[dict[str, Any]]:
    demo_customer_ids: set[int] = set()
    try:
        from app.services.message_store import get_demo_customer_ids

        demo_customer_ids = get_demo_customer_ids()
    except Exception:
        logger.warning("读取演示客户标记失败，将仅按档案标记过滤", exc_info=True)

    rows: list[dict[str, Any]] = []
    for doc in _iter_pipeline_docs():
        uid = _customer_id_from_doc(doc)
        if uid <= 0:
            continue
        is_demo = _is_demo_pipeline(doc, demo_customer_ids)
        if is_demo and not include_demo:
            continue
        stage = normalize_stage_id(str(doc.get("stage") or "idle"))
        contact = _contact_from_doc(doc)
        rows.append(
            {
                "customer_id": uid,
                "market_user_id": uid,
                "username": str(doc.get("username") or ""),
                "team_id": int(doc.get("team_id") or 0),
                "stage": stage,
                "stage_label": _STAGE_LABELS.get(stage, stage),
                "display_name": _display_name_from_doc(doc),
                "channel_sources": list(doc.get("channel_sources") or []),
                "ai_score": float(doc.get("ai_score") or 0.0),
                "ai_tags": list(doc.get("ai_tags") or []),
                "intake_sent": bool(doc.get("intake_sent")),
                "last_message_preview": str(doc.get("last_message_preview") or "")[:500],
                "updated_at": str(doc.get("updated_at") or ""),
                "created_at": str(doc.get("created_at") or doc.get("updated_at") or ""),
                # 扩展：手动维护的客户资料
                "name": contact["name"],
                "company": contact["company"],
                "email": contact["email"],
                "phone": contact["phone"],
                "owner": contact["owner"],
                "note": contact["note"],
                "source": contact["source"],
                "tags": contact["tags"],
                "is_demo": is_demo,
            }
        )
    rows.sort(key=lambda r: (r.get("updated_at") or "", r["customer_id"]), reverse=True)
    return rows


def build_pipeline_funnel_summary(
    *,
    max_clients_per_stage: int = 8,
    include_demo: bool = False,
) -> dict[str, Any]:
    counts = {s["id"]: 0 for s in PIPELINE_STAGES}
    clients_by_stage: dict[str, list[dict[str, Any]]] = {s["id"]: [] for s in PIPELINE_STAGES}
    for row in list_pipeline_client_summaries(include_demo=include_demo):
        st = normalize_stage_id(str(row.get("stage") or "idle"))
        if st not in counts:
            st = "idle"
        counts[st] += 1
        bucket = clients_by_stage[st]
        if len(bucket) < max(1, int(max_clients_per_stage)):
            bucket.append(row)
    stages = [
        {
            "id": s["id"],
            "label": s["label"],
            "count": counts.get(s["id"], 0),
            "clients": clients_by_stage.get(s["id"], []),
        }
        for s in PIPELINE_STAGES
    ]
    return {
        "stages": stages,
        "total_clients": sum(counts.values()),
        "counts": counts,
    }


def auto_advance_pipeline_if_ready(
    customer_id: int,
    *,
    username: str = "",
) -> tuple[dict[str, Any], bool]:
    doc = load_pipeline(customer_id, username=username)
    before = str(doc.get("stage") or "idle")
    advanced = False

    if doc.get("intake_submitted_at") and _stage_rank(doc.get("stage")) < _stage_rank("intake_done"):
        doc = set_pipeline_stage(
            customer_id,
            "intake_done",
            username=username,
            source="auto",
            note="表单已提交",
        )
        advanced = True
    elif doc.get("intake_sent") and _stage_rank(doc.get("stage")) < _stage_rank("intake"):
        doc = set_pipeline_stage(
            customer_id,
            "intake",
            username=username,
            source="auto",
            note="已发送采集话术",
        )
        advanced = True
    elif doc.get("connected_welcome_sent") and _stage_rank(doc.get("stage")) < _stage_rank("connected"):
        doc = set_pipeline_stage(
            customer_id,
            "connected",
            username=username,
            source="auto",
            note="建联欢迎语已发送",
        )
        advanced = True

    after = str(doc.get("stage") or "idle")
    return doc, advanced or before != after


def analyze_customer_pipeline(
    customer_id: int,
    *,
    username: str = "",
    message_texts: list[str] | None = None,
    has_binding: bool = False,
    intake_sent: bool = False,
) -> dict[str, Any]:
    doc = load_pipeline(customer_id, username=username)
    texts = [str(t or "").strip() for t in (message_texts or []) if str(t or "").strip()]
    if texts:
        doc["last_message_preview"] = texts[0][:500]
    if intake_sent:
        doc["intake_sent"] = True
    if has_binding and _stage_rank(doc.get("stage")) <= _stage_rank("idle"):
        doc["stage"] = "connected"
        _append_timeline(doc, "connected", "analyze", note="检测到群绑定")
    elif intake_sent and _stage_rank(doc.get("stage")) < _stage_rank("intake"):
        doc["stage"] = "intake"
        _append_timeline(doc, "intake", "analyze", note="已标记采集")
    return save_pipeline(doc)


def repair_pipeline_crm(customer_id: int, *, username: str = "") -> dict[str, Any]:
    doc = load_pipeline(customer_id, username=username)
    doc["crm_db_synced_at"] = _now_iso()
    return save_pipeline(doc)


def repair_all_pipelines() -> dict[str, Any]:
    repaired = 0
    for doc in _iter_pipeline_docs():
        uid = _customer_id_from_doc(doc)
        if uid <= 0:
            continue
        repair_pipeline_crm(uid, username=str(doc.get("username") or ""))
        repaired += 1
    return {"repaired": repaired}


# ---------------------------------------------------------------------------
# 客户资料 CRUD（基于 pipeline 档案）
# ---------------------------------------------------------------------------

# 手动创建客户的 ID 基线，避免与外部系统 ID（如 market_user_id）冲突
_MANUAL_CUSTOMER_ID_BASE = 90000


def next_customer_id() -> int:
    """为手动创建的客户分配一个新的 customer_id。"""
    max_id = 0
    for doc in _iter_pipeline_docs():
        max_id = max(max_id, _customer_id_from_doc(doc))
    return max(max_id, _MANUAL_CUSTOMER_ID_BASE) + 1


def _apply_profile(doc: dict[str, Any], profile: dict[str, Any]) -> None:
    """把传入的客户资料字段安全地写入 doc（白名单 + 清洗）。"""
    for key in _PROFILE_FIELDS:
        if profile.get(key) is not None:
            val = profile[key]
            doc[key] = val.strip() if isinstance(val, str) else val
    if profile.get("tags") is not None:
        doc["tags"] = [str(t).strip() for t in (profile.get("tags") or []) if str(t).strip()]
    if profile.get("channel_sources") is not None:
        doc["channel_sources"] = [str(c).strip() for c in (profile.get("channel_sources") or []) if str(c).strip()]
    if profile.get("is_demo") is not None:
        doc["is_demo"] = bool(profile.get("is_demo"))


def create_customer(profile: dict[str, Any], *, username: str = "") -> dict[str, Any]:
    """新建客户档案，返回保存后的 doc。"""
    uid = next_customer_id()
    doc = _default_pipeline(uid, username=username)
    doc["created_at"] = _now_iso()
    _apply_profile(doc, profile)
    stage = normalize_stage_id(profile.get("stage"))
    if stage in _STAGE_ORDER:
        doc["stage"] = stage
    _append_timeline(doc, doc["stage"], "manual", note="创建客户")
    return save_pipeline(doc)


def update_customer_profile(customer_id: int, profile: dict[str, Any], *, username: str = "") -> dict[str, Any]:
    """更新客户资料（含可选的阶段变更），返回保存后的 doc。"""
    doc = load_pipeline(int(customer_id), username=username)
    _apply_profile(doc, profile)
    stage = normalize_stage_id(profile.get("stage"))
    if stage and stage in _STAGE_ORDER and doc.get("stage") != stage:
        doc["stage"] = stage
        _append_timeline(doc, stage, "manual", note="资料更新")
    return save_pipeline(doc)


def add_customer_tag(customer_id: int, tag: str) -> dict[str, Any]:
    """给客户追加一个标签（去重）。"""
    doc = load_pipeline(int(customer_id))
    tags = [str(t) for t in (doc.get("tags") or [])]
    tag = str(tag).strip()
    if tag and tag not in tags:
        tags.append(tag)
    doc["tags"] = tags
    return save_pipeline(doc)


def remove_customer_tag(customer_id: int, tag: str) -> dict[str, Any]:
    """移除客户的某个标签。"""
    doc = load_pipeline(int(customer_id))
    tag = str(tag).strip()
    doc["tags"] = [str(t) for t in (doc.get("tags") or []) if str(t) != tag]
    return save_pipeline(doc)


def delete_pipeline(customer_id: int) -> bool:
    """删除客户档案（JSON 文件 + SQLite 快照）。"""
    uid = int(customer_id)
    deleted = False
    for root in _pipeline_roots():
        path = root / f"{uid}.json"
        if path.is_file():
            try:
                path.unlink()
                deleted = True
            except OSError:
                logger.warning("删除 pipeline 文件失败: %s", path, exc_info=True)
    try:
        from app.services.crm_store import delete_pipeline_from_sqlite

        delete_pipeline_from_sqlite(uid)
    except Exception:  # pragma: no cover - SQLite 清理失败不阻塞
        logger.debug("删除 SQLite pipeline 失败: customer_id=%s", uid, exc_info=True)
    return deleted


__all__ = [
    "PIPELINE_STAGES",
    "PipelineCrmGateError",
    "_STAGE_ORDER",
    "_pipeline_roots",
    "add_customer_tag",
    "analyze_customer_pipeline",
    "auto_advance_pipeline_if_ready",
    "build_pipeline_funnel_summary",
    "create_customer",
    "delete_pipeline",
    "list_pipeline_client_summaries",
    "load_pipeline",
    "next_customer_id",
    "normalize_stage_id",
    "remove_customer_tag",
    "repair_all_pipelines",
    "repair_pipeline_crm",
    "save_pipeline",
    "set_pipeline_stage",
    "update_customer_profile",
]
