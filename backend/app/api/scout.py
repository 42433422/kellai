"""v5 精准猎手 API 桩实现。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/kellai/scout", tags=["scout"])


class ScanBody(BaseModel):
    keyword: str = ""
    platform: str = "all"


class CommentBody(BaseModel):
    comment: str = ""


class DmBody(BaseModel):
    target_id: str = ""
    message: str = ""


class ConvertBody(BaseModel):
    target_id: str = ""


_TARGETS: list[dict[str, Any]] = [
    {"id": "st1", "platform": "douyin", "post_title": "CRM 系统选型指南", "comment": "有没有支持 AI 自动回复的？我们团队急需，怎么收费", "author": "创业小王", "intent_score": 92, "intent_level": "high", "reason": "明确表达购买需求并询价", "scanned_at": "2026-06-13T08:00:00Z", "source_url": "https://douyin.com/note/1", "followers": 12400, "region": "广东 · 深圳", "industry": "SaaS", "status": "new", "tags": ["急需", "怎么收费", "AI"]},
    {"id": "st2", "platform": "xiaohongshu", "post_title": "销售工具推荐 2026", "comment": "客来来有人用过吗？效果怎么样", "author": "运营Lisa", "intent_score": 78, "intent_level": "high", "reason": "主动询问产品口碑", "scanned_at": "2026-06-13T07:30:00Z", "source_url": "https://xiaohongshu.com/note/2", "followers": 8600, "region": "上海", "industry": "电商", "status": "contacted", "tags": ["有没有", "了解"]},
    {"id": "st3", "platform": "douyin", "post_title": "竞品X vs 竞品Y", "comment": "价格太贵了，有没有平替推荐", "author": "精打细算", "intent_score": 65, "intent_level": "medium", "reason": "价格敏感但有真实需求", "scanned_at": "2026-06-13T06:00:00Z", "source_url": "https://douyin.com/note/3", "followers": 3200, "region": "浙江 · 杭州", "industry": "零售", "status": "new", "tags": ["平替", "价格"]},
    {"id": "st5", "platform": "weibo", "post_title": "获客难，求支招", "comment": "私域获客成本太高了，求好用的工具，最好能自动跟进", "author": "增长黑客", "intent_score": 81, "intent_level": "high", "reason": "痛点明确，需求强烈", "scanned_at": "2026-06-13T04:20:00Z", "source_url": "https://weibo.com/note/5", "followers": 25800, "region": "北京", "industry": "互联网", "status": "replied", "tags": ["获客", "自动跟进"]},
]


@router.post("/scan")
def scan(body: ScanBody) -> dict:
    items = _TARGETS
    if body.platform and body.platform != "all":
        items = [t for t in items if t["platform"] == body.platform]
    if body.keyword:
        items = [t for t in items if body.keyword in t["comment"] or body.keyword in t["post_title"]]
    return {"success": True, "data": items}


@router.post("/intent-score")
def intent_score(body: CommentBody) -> dict:
    high_kw = ["急需", "购买", "报价", "怎么收费", "有没有"]
    med_kw = ["了解", "推荐", "对比", "效果", "平替", "想找"]
    score = 30
    keywords: list[str] = []
    for kw in high_kw:
        if kw in body.comment:
            score += 20
            keywords.append(kw)
    for kw in med_kw:
        if kw in body.comment:
            score += 10
            keywords.append(kw)
    score = min(100, score)
    level = "high" if score >= 70 else "medium" if score >= 45 else "low"
    return {"success": True, "data": {"comment": body.comment, "score": score, "level": level, "keywords": keywords, "reason": f"命中 {len(keywords)} 个意向关键词，综合判定为 {level}"}}


@router.post("/auto-dm")
def auto_dm(body: DmBody) -> dict:
    for t in _TARGETS:
        if t["id"] == body.target_id and t["status"] == "new":
            t["status"] = "contacted"
    return {"success": True, "data": {"success": True, "message": "已发送私信"}}


@router.post("/convert")
def convert(body: ConvertBody) -> dict:
    for t in _TARGETS:
        if t["id"] == body.target_id:
            t["status"] = "converted"
            return {"success": True, "data": {"success": True, "message": f"@{t['author']} 已转入 CRM 客户库"}}
    return {"success": True, "data": {"success": False, "message": "目标不存在"}}


@router.get("/sentiment")
def sentiment() -> dict:
    return {
        "success": True,
        "data": [
            {"id": "s1", "type": "hotspot", "title": "AI 获客工具热度上升", "summary": "行业讨论量周环比 +45%", "severity": "high", "timestamp": "2026-06-13T09:00:00Z", "sentiment": "positive", "sentiment_score": 82, "volume": 1240, "volume_change": 45, "source": "抖音 / 小红书", "url": "https://example.com/s1", "keywords": ["AI获客", "测评"]},
            {"id": "s2", "type": "competitor", "title": "竞品 X 发布评论区自动触达", "summary": "部分用户反馈触达过于频繁", "severity": "medium", "timestamp": "2026-06-12T15:00:00Z", "sentiment": "negative", "sentiment_score": 38, "volume": 680, "volume_change": 12, "source": "微博", "url": "https://example.com/s2", "keywords": ["竞品X", "骚扰"]},
            {"id": "s3", "type": "opportunity", "title": "教育行业数字化招标季", "summary": "3 个大型招标即将截止", "severity": "high", "timestamp": "2026-06-12T10:00:00Z", "sentiment": "positive", "sentiment_score": 76, "volume": 420, "volume_change": 28, "source": "招标网", "url": "https://example.com/s3", "keywords": ["招标", "教育"]},
        ],
    }


@router.get("/sentiment-overview")
def sentiment_overview() -> dict:
    return {
        "success": True,
        "data": {
            "total": 3940,
            "positive_pct": 52,
            "neutral_pct": 31,
            "negative_pct": 17,
            "volume_change": 23,
            "volume_trend": [
                {"date": "06-07", "count": 280},
                {"date": "06-08", "count": 320},
                {"date": "06-09", "count": 410},
                {"date": "06-10", "count": 380},
                {"date": "06-11", "count": 520},
                {"date": "06-12", "count": 610},
                {"date": "06-13", "count": 720},
            ],
            "top_keywords": [
                {"word": "AI获客", "count": 412},
                {"word": "私域", "count": 356},
                {"word": "客户管理", "count": 298},
                {"word": "自动跟进", "count": 241},
                {"word": "竞品X", "count": 187},
            ],
            "watch_terms": ["客来来", "AI获客", "私域运营", "CRM", "竞品X", "竞品Y"],
        },
    }


@router.get("/trace")
def trace(target_id: str = "st1") -> dict:
    return {
        "success": True,
        "data": {
            "target_id": target_id,
            "steps": [
                {"action": "评论巡检", "timestamp": "2026-06-10T08:00:00Z", "result": "AI 发现高意向评论"},
                {"action": "意向评分", "timestamp": "2026-06-10T08:01:00Z", "result": "综合评分 92，判定为高意向"},
                {"action": "自动私信", "timestamp": "2026-06-10T08:05:00Z", "result": "已发送个性化触达话术"},
                {"action": "客户回复", "timestamp": "2026-06-10T14:00:00Z", "result": "客户表达进一步兴趣"},
                {"action": "转入漏斗", "timestamp": "2026-06-11T09:00:00Z", "result": "已转入 CRM，阶段：已建联"},
            ],
            "converted": True,
        },
    }


@router.post("/match-script")
def match_script(body: CommentBody) -> dict:
    return {"success": True, "data": {"scripts": ["您好，感谢关注！方便私信详聊吗？", "我可以为您安排 15 分钟产品演示"]}}
