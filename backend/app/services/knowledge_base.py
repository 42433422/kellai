"""Deterministic knowledge-base retrieval for客服回复 and audits."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data_root() -> Path:
    from app.services.llm_config import _data_root as llm_data_root

    return llm_data_root()


def _kb_path() -> Path:
    return _data_root() / "knowledge_base.json"


def _read_disk() -> dict[str, Any]:
    path = _kb_path()
    if not path.is_file():
        return {"articles": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"articles": []}
    if not isinstance(data, dict):
        return {"articles": []}
    articles = data.get("articles")
    if not isinstance(articles, list):
        data["articles"] = []
    return data


def _write_disk(data: dict[str, Any]) -> dict[str, Any]:
    path = _kb_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def _tokens(text: str) -> set[str]:
    raw = str(text or "").lower()
    pieces = set(re.findall(r"[a-z0-9_]{2,}", raw))
    cn_terms = (
        "价格", "报价", "优惠", "折扣", "合同", "付款", "签约", "交付", "培训", "企业微信",
        "企微", "抖音", "小程序", "私信", "托管", "知识库", "退款", "售后", "发票", "部署",
        "上线", "账号", "渠道", "客服", "自动回复", "人工", "风险", "合规", "质检",
    )
    pieces.update(term for term in cn_terms if term in raw)
    return pieces


def list_articles() -> list[dict[str, Any]]:
    data = _read_disk()
    return [a for a in data.get("articles", []) if isinstance(a, dict)]


def upsert_article(payload: dict[str, Any]) -> dict[str, Any]:
    data = _read_disk()
    articles = [a for a in data.get("articles", []) if isinstance(a, dict)]
    article_id = str(payload.get("id") or "").strip() or f"kb_{secrets.token_hex(6)}"
    tags = [str(x).strip() for x in payload.get("tags", []) if str(x).strip()] if isinstance(payload.get("tags"), list) else []
    article = {
        "id": article_id,
        "title": str(payload.get("title") or "").strip()[:160],
        "content": str(payload.get("content") or "").strip()[:12000],
        "tags": tags[:20],
        "source": str(payload.get("source") or "manual").strip()[:80],
        "updated_at": _now_iso(),
    }
    if not article["title"]:
        article["title"] = "未命名知识"
    articles = [a for a in articles if str(a.get("id") or "") != article_id]
    articles.append(article)
    data["articles"] = articles
    _write_disk(data)
    return article


def delete_article(article_id: str) -> bool:
    data = _read_disk()
    before = [a for a in data.get("articles", []) if isinstance(a, dict)]
    after = [a for a in before if str(a.get("id") or "") != str(article_id)]
    data["articles"] = after
    _write_disk(data)
    return len(after) != len(before)


def search_articles(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for article in list_articles():
        haystack = " ".join(
            [
                str(article.get("id") or ""),
                str(article.get("title") or ""),
                str(article.get("content") or ""),
                " ".join(str(x) for x in (article.get("tags") or [])),
            ]
        )
        article_tokens = _tokens(haystack)
        overlap = query_tokens & article_tokens
        if not overlap:
            continue
        score = len(overlap) / max(len(query_tokens), 1)
        title = str(article.get("title") or "")
        if any(token in title for token in overlap):
            score += 0.2
        scored.append((score, article))
    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[dict[str, Any]] = []
    for score, article in scored[: max(1, min(limit, 20))]:
        out = dict(article)
        out["score"] = round(score, 4)
        out["snippet"] = str(article.get("content") or "")[:240]
        results.append(out)
    return results


def suggest_answer(query: str, *, customer_context: dict[str, Any] | None = None, limit: int = 3) -> dict[str, Any]:
    hits = search_articles(query, limit=limit)
    if not hits:
        return {
            "answer": "知识库暂未命中，请补充相关产品、价格、交付或售后知识后再回复客户。",
            "matched": False,
            "sources": [],
            "confidence": 0.0,
        }
    top = hits[0]
    stage = str((customer_context or {}).get("stage_label") or (customer_context or {}).get("stage") or "")
    prefix = f"结合客户当前阶段（{stage}），" if stage else ""
    answer = (
        f"{prefix}可按知识库《{top.get('title')}》回复："
        f"{str(top.get('content') or '').strip()[:500]}"
    )
    if len(hits) > 1:
        answer += f"\n\n可补充参考：{', '.join(str(item.get('title') or '') for item in hits[1:])}"
    return {
        "answer": answer,
        "matched": True,
        "sources": [{"id": item.get("id"), "title": item.get("title"), "score": item.get("score")} for item in hits],
        "confidence": min(1.0, float(top.get("score") or 0.0)),
    }


__all__ = [
    "_kb_path",
    "_read_disk",
    "_write_disk",
    "delete_article",
    "list_articles",
    "search_articles",
    "suggest_answer",
    "upsert_article",
]
