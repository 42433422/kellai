"""v8 开放平台 API 桩实现。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/kellai/open", tags=["open"])

_keys: list[dict[str, Any]] = [{"id": "key1", "name": "生产环境", "key_prefix": "kl_live_****", "scopes": ["customers:read"], "created_at": "2026-01-15T00:00:00Z"}]


class KeyBody(BaseModel):
    name: str = "新密钥"
    scopes: list[str] = Field(default_factory=list)


class WebhookBody(BaseModel):
    url: str = ""
    events: list[str] = Field(default_factory=list)


class ReviewBody(BaseModel):
    app_name: str = ""


@router.get("/api-keys")
def api_keys() -> dict:
    return {"success": True, "data": _keys}


@router.post("/api-keys")
def create_key(body: KeyBody) -> dict:
    key = {"id": f"key_{len(_keys)}", "name": body.name, "key_prefix": "kl_live_****", "scopes": body.scopes, "created_at": "2026-06-12T00:00:00Z"}
    _keys.append(key)
    return {"success": True, "data": key}


@router.get("/plugins")
def plugins() -> dict:
    return {"success": True, "data": [{"id": "p1", "name": "企业微信增强", "description": "消息同步", "author": "Kellai", "category": "channel", "rating": 4.8, "installs": 1250, "price": 0, "installed": True}]}


@router.post("/plugins/publish")
def publish_plugin(body: dict) -> dict:
    return {"success": True, "data": {"id": "p_new", "name": body.get("name", "新插件"), "description": "", "author": "开发者", "category": "other", "rating": 0, "installs": 0, "price": 0, "installed": False}}


@router.post("/plugins/install")
def install_plugin(body: dict) -> dict:
    return {"success": True, "data": {"installed": True}}


@router.get("/isv")
def isv() -> dict:
    return {"success": True, "data": [{"id": "isv1", "name": "CloudTech", "tier": "gold", "solutions": 12, "certified": True}]}


@router.post("/webhooks")
def webhooks(body: WebhookBody) -> dict:
    return {"success": True, "data": {"id": "owh_1", "url": body.url, "events": body.events, "secret": "whsec_xxx", "active": True}}


@router.get("/events")
def events() -> dict:
    return {"success": True, "data": [{"id": "ev1", "event_type": "customer.created", "description": "新客户", "subscribed": True}]}


@router.get("/app-builder")
def app_builder() -> dict:
    return {"success": True, "data": [{"id": "at1", "name": "跟进表单", "description": "自定义字段", "fields": []}]}


@router.get("/docs")
def docs() -> dict:
    return {"success": True, "data": {"endpoints": [{"method": "GET", "path": "/api/kellai/customers", "description": "客户列表"}]}}


@router.post("/review")
def review(body: ReviewBody) -> dict:
    return {"success": True, "data": {"app_id": "app_1", "app_name": body.app_name, "status": "pending", "submitted_at": "2026-06-12T00:00:00Z"}}
