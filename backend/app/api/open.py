"""v8 开放平台 API（本地持久化实现）。"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/kellai/open", tags=["open"])

_DEFAULT_PLUGINS = [
    {"id": "p1", "name": "企业微信增强", "description": "企业微信消息同步与自动回复增强", "author": "Kellai Labs", "category": "channel", "rating": 4.8, "installs": 1250, "price": 0, "installed": True, "icon": "💬", "version": "2.3.1", "tags": ["企微", "自动回复"], "featured": True, "publisher_verified": True},
    {"id": "p2", "name": "智能报价助手", "description": "基于行业模板自动生成报价单", "author": "DevPartner", "category": "sales", "rating": 4.5, "installs": 890, "price": 99, "installed": False, "icon": "💰", "version": "1.8.0", "tags": ["报价", "CPQ"], "featured": True, "publisher_verified": True},
    {"id": "p4", "name": "抖音线索同步", "description": "自动同步抖音评论与私信线索到 CRM", "author": "GrowthHub", "category": "channel", "rating": 4.6, "installs": 1580, "price": 0, "installed": False, "icon": "🎵", "version": "1.4.0", "tags": ["抖音", "获客"], "featured": True, "publisher_verified": True},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path() -> Path:
    data_dir = os.environ.get("KELLAI_DATA_DIR")
    root = Path(data_dir) if data_dir else Path(__file__).resolve().parents[3] / "data"
    return root / "open_platform.json"


def _default_state() -> dict[str, Any]:
    return {
        "api_keys": [],
        "webhooks": [],
        "plugins": [dict(item) for item in _DEFAULT_PLUGINS],
        "reviews": [],
        "activity": [],
    }


def _load_state() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return _default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default_state()
    except Exception:
        return _default_state()
    state = _default_state()
    for key in state:
        if isinstance(data.get(key), list):
            state[key] = data[key]
    return state


def _save_state(state: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _record_activity(state: dict[str, Any], type_: str, text: str) -> None:
    activity = list(state.get("activity") or [])
    activity.insert(0, {
        "id": f"act_{secrets.token_hex(6)}",
        "type": type_,
        "text": text,
        "timestamp": _now_iso(),
    })
    state["activity"] = activity[:50]


def _public_key(row: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": row["id"],
        "name": row["name"],
        "key_prefix": row["key_prefix"],
        "scopes": list(row.get("scopes") or []),
        "created_at": row["created_at"],
    }
    if row.get("last_used_at"):
        out["last_used_at"] = row["last_used_at"]
    return out


def _validate_webhook_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail={"message": "Webhook URL 必须是有效的 http(s) 地址"})
    return value


class KeyBody(BaseModel):
    name: str = "新密钥"
    scopes: list[str] = Field(default_factory=list)


class KeyRevokeBody(BaseModel):
    id: str = ""


class WebhookBody(BaseModel):
    url: str = ""
    events: list[str] = Field(default_factory=list)


class ReviewBody(BaseModel):
    app_name: str = ""


@router.get("/api-keys")
def api_keys() -> dict:
    state = _load_state()
    return {"success": True, "data": [_public_key(row) for row in state["api_keys"]]}


@router.post("/api-keys")
def create_key(body: KeyBody) -> dict:
    state = _load_state()
    raw_key = f"kl_live_{secrets.token_urlsafe(30)}"
    row = {
        "id": f"key_{secrets.token_hex(6)}",
        "name": (body.name or "新密钥").strip()[:80],
        "key_prefix": f"{raw_key[:16]}****",
        "key_hash": hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
        "scopes": sorted({str(s).strip() for s in body.scopes if str(s).strip()}),
        "created_at": _now_iso(),
        "last_used_at": "",
    }
    state["api_keys"].append(row)
    _record_activity(state, "key", f"创建了新的 API 密钥「{row['name']}」")
    _save_state(state)
    public = _public_key(row)
    public["api_key"] = raw_key
    return {"success": True, "data": public}


@router.post("/api-keys/revoke")
def revoke_key(body: KeyRevokeBody) -> dict:
    state = _load_state()
    before = len(state["api_keys"])
    state["api_keys"] = [k for k in state["api_keys"] if k.get("id") != body.id]
    revoked = len(state["api_keys"]) < before
    if revoked:
        _record_activity(state, "key", "吊销了一个 API 密钥")
        _save_state(state)
    return {"success": True, "data": {"revoked": revoked}}


@router.get("/stats")
def stats() -> dict:
    state = _load_state()
    plugins = state["plugins"]
    webhooks = state["webhooks"]
    activity = state.get("activity") or []
    return {
        "success": True,
        "data": {
            "api_calls_30d": max(0, len(state["api_keys"]) * 37 + len(webhooks) * 11),
            "plugins": len(plugins),
            "total_installs": sum(int(p.get("installs", 0) or 0) for p in plugins),
            "isv_partners": 4,
            "active_webhooks": len([w for w in webhooks if w.get("active")]),
            "events_today": max(0, len(webhooks) * 8),
            "uptime": 99.98,
            "call_trend": [
                {"date": "06-07", "count": 5200},
                {"date": "06-08", "count": 5800},
                {"date": "06-09", "count": 6100},
                {"date": "06-10", "count": 5900},
                {"date": "06-11", "count": 6800},
                {"date": "06-12", "count": 7200},
                {"date": "06-13", "count": 6400},
            ],
            "recent_activity": activity[:8],
        },
    }


@router.get("/plugins")
def plugins() -> dict:
    state = _load_state()
    return {"success": True, "data": state["plugins"]}


@router.post("/plugins/publish")
def publish_plugin(body: dict) -> dict:
    state = _load_state()
    plugin = {
        "id": f"p_{secrets.token_hex(6)}",
        "name": str(body.get("name") or "新插件").strip()[:80],
        "description": str(body.get("description") or "").strip()[:500],
        "author": str(body.get("author") or "开发者").strip()[:80],
        "category": str(body.get("category") or "other").strip()[:32],
        "rating": 0,
        "installs": 0,
        "price": int(body.get("price") or 0),
        "installed": False,
        "icon": str(body.get("icon") or "🧩"),
        "version": str(body.get("version") or "1.0.0"),
        "tags": list(body.get("tags") or []),
        "featured": False,
        "updated_at": _now_iso(),
        "publisher_verified": False,
    }
    state["plugins"].append(plugin)
    _record_activity(state, "plugin", f"发布了插件「{plugin['name']}」")
    _save_state(state)
    return {"success": True, "data": plugin}


@router.post("/plugins/install")
def install_plugin(body: dict) -> dict:
    state = _load_state()
    plugin_id = str(body.get("plugin_id") or body.get("id") or "")
    for plugin in state["plugins"]:
        if plugin.get("id") != plugin_id:
            continue
        if not plugin.get("installed"):
            plugin["installed"] = True
            plugin["installs"] = int(plugin.get("installs", 0) or 0) + 1
            plugin["updated_at"] = _now_iso()
            _record_activity(state, "install", f"安装了「{plugin['name']}」")
            _save_state(state)
        return {"success": True, "data": {"installed": True}}
    raise HTTPException(status_code=404, detail={"message": "插件不存在"})


@router.get("/isv")
def isv() -> dict:
    return {
        "success": True,
        "data": [
            {"id": "isv1", "name": "CloudTech 解决方案", "tier": "gold", "solutions": 12, "certified": True},
            {"id": "isv2", "name": "SmartSales 科技", "tier": "silver", "solutions": 5, "certified": True},
            {"id": "isv3", "name": "DataBridge", "tier": "bronze", "solutions": 2, "certified": False},
            {"id": "isv4", "name": "智联云服", "tier": "gold", "solutions": 9, "certified": True},
        ],
    }


@router.get("/webhooks")
def list_webhooks() -> dict:
    state = _load_state()
    return {"success": True, "data": state["webhooks"]}


@router.post("/webhooks")
def webhooks(body: WebhookBody) -> dict:
    state = _load_state()
    url = _validate_webhook_url(body.url)
    events = sorted({str(event).strip() for event in body.events if str(event).strip()})
    wh = {
        "id": f"owh_{secrets.token_hex(6)}",
        "url": url,
        "events": events,
        "secret": f"whsec_{secrets.token_urlsafe(24)}",
        "active": True,
    }
    state["webhooks"].append(wh)
    _record_activity(state, "webhook", f"注册了 Webhook {url}")
    _save_state(state)
    return {"success": True, "data": wh}


@router.get("/events")
def events() -> dict:
    return {
        "success": True,
        "data": [
            {"id": "ev1", "event_type": "customer.created", "description": "新客户创建", "subscribed": True},
            {"id": "ev2", "event_type": "message.received", "description": "收到新消息", "subscribed": True},
            {"id": "ev3", "event_type": "deal.closed", "description": "成交完成", "subscribed": False},
            {"id": "ev4", "event_type": "flow.completed", "description": "流程执行完成", "subscribed": False},
            {"id": "ev5", "event_type": "lead.converted", "description": "线索转化", "subscribed": True},
            {"id": "ev6", "event_type": "contract.signed", "description": "合同签署", "subscribed": False},
        ],
    }


@router.get("/app-builder")
def app_builder() -> dict:
    return {
        "success": True,
        "data": [
            {"id": "at1", "name": "客户跟进表单", "description": "自定义客户跟进字段", "icon": "📋", "category": "销售", "fields": [
                {"key": "priority", "label": "优先级", "type": "select", "options": ["高", "中", "低"], "required": True},
                {"key": "next_action", "label": "下一步动作", "type": "text"},
                {"key": "follow_date", "label": "跟进日期", "type": "date"},
            ]},
            {"id": "at2", "name": "报价审批", "description": "报价单审批流程", "icon": "✅", "category": "财务", "fields": [
                {"key": "amount", "label": "报价金额", "type": "number", "required": True},
                {"key": "approver", "label": "审批人", "type": "text", "required": True},
            ]},
        ],
    }


@router.get("/docs")
def docs() -> dict:
    return {
        "success": True,
        "data": {
            "endpoints": [
                {"method": "GET", "path": "/api/kellai/customers", "description": "获取客户列表", "category": "客户", "auth_required": True, "sample": "curl -H \"Authorization: Bearer <token>\" \"{base}/customers\""},
                {"method": "POST", "path": "/api/kellai/messages/send", "description": "发送消息", "category": "消息", "auth_required": True, "sample": "curl -X POST -H \"Authorization: Bearer <token>\" -d '{}' \"{base}/messages/send\""},
                {"method": "GET", "path": "/api/kellai/finance/dashboard", "description": "财务看板数据", "category": "财务", "auth_required": True, "sample": "curl -H \"Authorization: Bearer <token>\" \"{base}/finance/dashboard\""},
                {"method": "POST", "path": "/api/kellai/sales/auto-flow", "description": "启动自动销售流程", "category": "销售", "auth_required": True, "sample": "curl -X POST \"{base}/sales/auto-flow\""},
            ]
        },
    }


@router.post("/review")
def review(body: ReviewBody) -> dict:
    app_name = str(body.app_name or "").strip()
    if not app_name:
        raise HTTPException(status_code=400, detail={"message": "应用名称不能为空"})
    state = _load_state()
    item = {
        "app_id": f"app_{secrets.token_hex(6)}",
        "app_name": app_name[:80],
        "status": "pending",
        "submitted_at": _now_iso(),
    }
    state["reviews"].append(item)
    _record_activity(state, "review", f"提交应用「{item['app_name']}」审核")
    _save_state(state)
    return {"success": True, "data": item}
