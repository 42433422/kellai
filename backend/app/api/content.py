"""v4 内容矩阵 API 桩实现。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/kellai/content", tags=["content"])


class TopicBody(BaseModel):
    topic: str = ""
    prompt: str = ""


class PublishBody(BaseModel):
    content_id: str = ""
    platforms: list[str] = Field(default_factory=list)


@router.post("/generate-text")
def generate_text(body: TopicBody) -> dict:
    return {"success": True, "data": {"id": "c_new", "type": "text", "title": body.topic, "body": f"【{body.topic}】营销推文", "status": "draft", "platforms": [], "created_at": "2026-06-12T00:00:00Z"}}


@router.post("/generate-image")
def generate_image(body: TopicBody) -> dict:
    return {"success": True, "data": {"id": "img_new", "type": "image", "title": body.prompt, "image_url": "https://picsum.photos/800/600", "status": "draft", "platforms": [], "created_at": "2026-06-12T00:00:00Z"}}


@router.post("/generate-video-script")
def generate_video_script(body: TopicBody) -> dict:
    return {"success": True, "data": {"id": "vs_new", "type": "video_script", "title": body.topic, "body": "短视频脚本...", "status": "draft", "platforms": [], "created_at": "2026-06-12T00:00:00Z"}}


@router.post("/publish")
def publish(body: PublishBody) -> dict:
    return {"success": True, "data": {"id": body.content_id, "status": "published", "platforms": body.platforms}}


@router.post("/ad-strategy")
def ad_strategy() -> dict:
    return {"success": True, "data": {"recommended_channels": [{"channel": "douyin", "label": "抖音", "score": 92, "best_hours": ["19:00-22:00"]}], "budget_split": [{"channel": "douyin", "pct": 40}], "reasoning": "基于受众画像推荐"}}


@router.get("/analytics")
def analytics() -> dict:
    return {"success": True, "data": {"items": [], "totals": {"views": 57500, "likes": 4090, "conversions": 123}}}


@router.post("/ab-test")
def ab_test() -> dict:
    return {"success": True, "data": {"id": "ab1", "name": "标题测试", "status": "running", "variants": []}}


@router.get("/list")
def list_content() -> dict:
    return {"success": True, "data": []}
