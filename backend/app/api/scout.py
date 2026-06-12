"""v5 精准猎手 API 桩实现。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/kellai/scout", tags=["scout"])


class ScanBody(BaseModel):
    keyword: str = ""


class CommentBody(BaseModel):
    comment: str = ""


class DmBody(BaseModel):
    target_id: str = ""
    message: str = ""


@router.post("/scan")
def scan(body: ScanBody) -> dict:
    return {"success": True, "data": [{"id": "st1", "platform": "douyin", "post_title": "CRM选型", "comment": "有没有AI自动回复的", "author": "小王", "intent_score": 92, "intent_level": "high", "reason": "明确需求", "scanned_at": "2026-06-12T00:00:00Z"}]}


@router.post("/intent-score")
def intent_score(body: CommentBody) -> dict:
    return {"success": True, "data": {"comment": body.comment, "score": 75, "level": "high", "keywords": [], "reason": "高意向"}}


@router.post("/auto-dm")
def auto_dm(body: DmBody) -> dict:
    return {"success": True, "data": {"success": True, "message": f"已向目标发送私信"}}


@router.get("/sentiment")
def sentiment() -> dict:
    return {"success": True, "data": [{"id": "s1", "type": "hotspot", "title": "AI获客热度上升", "summary": "讨论量+45%", "severity": "high", "timestamp": "2026-06-12T00:00:00Z"}]}


@router.get("/trace")
def trace(target_id: str = "st1") -> dict:
    return {"success": True, "data": {"target_id": target_id, "steps": [], "converted": True}}


@router.post("/match-script")
def match_script(body: CommentBody) -> dict:
    return {"success": True, "data": {"scripts": ["您好，感谢关注！"]}}
