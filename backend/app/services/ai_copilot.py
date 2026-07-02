"""客来来 AI 跟单引擎 — 意图识别、话术推荐、自动回复、客户画像、跟进提醒。"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.pipeline import (
    PIPELINE_STAGES,
    _STAGE_ORDER,
    _display_name_from_doc,
    _iter_pipeline_docs,
    _stage_rank,
    load_pipeline,
)

logger = logging.getLogger(__name__)

# ── 意图分类 ──────────────────────────────────────────────────────────────
INTENT_TYPES = [
    "inquiry",      # 询价
    "complaint",     # 抱怨
    "confirm",       # 确认
    "chitchat",      # 闲聊
    "urgent",        # 催促
    "negotiation",   # 议价
    "interest",      # 表达兴趣
    "rejection",     # 拒绝
    "other",         # 其他
]

INTENT_LABELS = {
    "inquiry": "询价", "complaint": "抱怨", "confirm": "确认",
    "chitchat": "闲聊", "urgent": "催促", "negotiation": "议价",
    "interest": "表达兴趣", "rejection": "拒绝", "other": "其他",
}

# 高意向意图（触发桌面通知）
HIGH_INTENT_TYPES = {"inquiry", "interest", "urgent", "negotiation"}

# ── LLM Provider 配置 ────────────────────────────────────────────────────
_LLM_PROVIDERS: list[dict[str, str]] = [
    {
        "key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    {
        "key_env": "OPENAI_API_KEY",
        "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    },
    {
        "key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": os.environ.get("DASHSCOPE_MODEL", "qwen-plus"),
    },
    {
        "key_env": "MOONSHOT_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    {
        "key_env": "SILICONFLOW_API_KEY",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": os.environ.get("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3"),
    },
]

# ── 关键词规则（LLM 未配置时的 fallback）──────────────────────────────────
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "inquiry": ["价格", "报价", "多少钱", "费用", "收费", "单价", "总价", "预算", "成本", "怎么卖"],
    "negotiation": ["太贵", "便宜点", "优惠", "折扣", "让利", "降价", "还价", "砍价", "能不能少"],
    "urgent": ["什么时候", "催", "急", "赶紧", "快点", "尽快", "等不了", "马上", "加急"],
    "complaint": ["投诉", "不满", "差评", "问题", "质量差", "服务差", "态度差", "太慢", "不靠谱"],
    "confirm": ["确认", "好的", "没问题", "可以", "行", "同意", "OK", "收到"],
    "interest": ["感兴趣", "想了解", "想看看", "介绍一下", "详情", "方案", "合作", "有意"],
    "rejection": ["不需要", "不考虑", "算了", "不要", "放弃", "没兴趣", "暂时不用", "以后再说"],
    "chitchat": ["你好", "在吗", "嗨", "早上好", "下午好", "辛苦", "谢谢", "周末"],
}

# 敏感关键词（自动回复不可直接发送）
_SENSITIVE_KEYWORDS = [
    "价格承诺", "保证", "合同条款", "签约", "交付时间", "到货时间",
    "赔偿", "违约", "法律", "担保", "保底",
]

# ── 模板话术（LLM 未配置时的 fallback）───────────────────────────────────
_TEMPLATE_REPLIES: dict[str, list[dict[str, Any]]] = {
    "inquiry": [
        {"text": "感谢您的咨询！我这边马上为您准备报价方案，稍后发给您。", "style": "professional", "confidence": 0.8},
        {"text": "您好，关于价格方面我们可以根据您的具体需求来定，方便说下大概的数量和要求吗？", "style": "friendly", "confidence": 0.7},
        {"text": "收到，我这边给您出个报价单，请稍等。", "style": "direct", "confidence": 0.75},
    ],
    "negotiation": [
        {"text": "理解您的想法，我这边帮您申请一下最优价格，稍后回复您。", "style": "professional", "confidence": 0.75},
        {"text": "价格方面我们还有商量的空间，让我看看能给到您什么优惠方案。", "style": "friendly", "confidence": 0.7},
        {"text": "好的，我去跟领导申请一下，看能不能再优惠一些。", "style": "direct", "confidence": 0.65},
    ],
    "urgent": [
        {"text": "非常抱歉让您久等了！我这边马上加急处理，有进展第一时间通知您。", "style": "professional", "confidence": 0.85},
        {"text": "收到您的催促，我立刻跟进这个事情，尽快给您一个答复。", "style": "friendly", "confidence": 0.8},
        {"text": "好的，我现在就去处理，稍后给您反馈。", "style": "direct", "confidence": 0.75},
    ],
    "complaint": [
        {"text": "非常抱歉给您带来不好的体验，我这边立刻核实情况并跟进处理。", "style": "professional", "confidence": 0.85},
        {"text": "您说的问题我记下了，马上反馈给相关部门，一定给您一个满意的答复。", "style": "friendly", "confidence": 0.8},
        {"text": "抱歉，我这边马上处理您反馈的问题。", "style": "direct", "confidence": 0.75},
    ],
    "interest": [
        {"text": "很高兴您对我们的产品感兴趣！我这边给您发一份详细方案，方便您参考。", "style": "professional", "confidence": 0.8},
        {"text": "太好了！我来给您做个详细介绍，您看方便电话还是微信沟通？", "style": "friendly", "confidence": 0.75},
        {"text": "好的，我这边整理一下资料发给您。", "style": "direct", "confidence": 0.7},
    ],
    "default": [
        {"text": "收到您的消息，我这边稍后回复您。", "style": "professional", "confidence": 0.6},
        {"text": "好的，我看到了，马上处理。", "style": "friendly", "confidence": 0.55},
        {"text": "收到，稍后回复。", "style": "direct", "confidence": 0.5},
    ],
}


# ── 内部工具函数 ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_llm_client() -> tuple[str, Any]:
    """获取 LLM 客户端配置，返回 (provider_name, config_dict)。

    支持 deepseek, openai, dashscope, moonshot, siliconflow。
    优先使用环境变量，其次使用设置页保存的本地配置。
    """
    try:
        from app.services.llm_config import effective_config

        cfg = effective_config()
        if cfg.get("api_key"):
            return str(cfg.get("provider") or ""), {
                "api_key": str(cfg["api_key"]),
                "base_url": str(cfg.get("base_url") or ""),
                "model": str(cfg.get("model") or ""),
            }
    except Exception:
        logger.debug("读取本地 LLM 配置失败，回退到环境变量", exc_info=True)

    # 兜底兼容旧部署：直接扫描历史环境变量。
    for prov in _LLM_PROVIDERS:
        api_key = (os.environ.get(prov["key_env"]) or "").strip()
        if api_key:
            provider_name = prov["key_env"].replace("_API_KEY", "").lower()
            if provider_name == "dashscope":
                provider_name = "qwen"
            return provider_name, {
                "api_key": api_key,
                "base_url": prov["base_url"],
                "model": prov["model"],
            }
    return "", {}


def _call_llm(prompt: str, system_prompt: str = "", max_tokens: int = 1024) -> str:
    """调用 LLM，返回文本响应。使用 httpx 直接调用各 provider 的 API。"""
    provider_name, config = _get_llm_client()
    if not config:
        return ""

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": config["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    try:
        from app.services.llm_config import needs_mimo_thinking_disabled

        if needs_mimo_thinking_disabled(provider_name, str(config.get("base_url") or "")):
            payload["thinking"] = {"type": "disabled"}
    except Exception:
        logger.debug("检查 MiMo thinking 兼容参数失败", exc_info=True)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }

    url = f"{config['base_url']}/chat/completions"

    try:
        from app.services.llm_config import trust_env_proxy

        with httpx.Client(timeout=15.0, trust_env=trust_env_proxy()) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            message = (data.get("choices") or [{}])[0].get("message", {})
            content = message.get("content") or message.get("reasoning_content") or ""
            return content.strip()
    except httpx.TimeoutException:
        logger.warning("LLM 调用超时 (provider=%s)", provider_name)
    except httpx.HTTPStatusError as exc:
        logger.warning("LLM 调用 HTTP 错误 (provider=%s, status=%s)", provider_name, exc.response.status_code)
    except Exception:
        logger.exception("LLM 调用异常 (provider=%s)", provider_name)
    return ""


def _keyword_match_intent(message: str) -> tuple[str, float, list[str]]:
    """关键词规则匹配意图，返回 (intent, confidence, keywords)。"""
    matched: list[tuple[str, list[str]]] = []
    for intent, keywords in _INTENT_KEYWORDS.items():
        found = [kw for kw in keywords if kw in message]
        if found:
            matched.append((intent, found))

    if not matched:
        return "other", 0.3, []

    # 按匹配关键词数量排序，取最佳
    matched.sort(key=lambda x: len(x[1]), reverse=True)
    best_intent, best_keywords = matched[0]
    confidence = min(0.5 + 0.1 * len(best_keywords), 0.9)
    return best_intent, confidence, best_keywords


def _parse_json_from_llm(text: str) -> dict[str, Any] | list[Any] | None:
    """从 LLM 响应中提取 JSON，支持 markdown 代码块包裹。"""
    if not text:
        return None
    # 尝试提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidate = m.group(1).strip() if m else text.strip()
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        # 尝试找到第一个 { 和最后一个 }
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except (json.JSONDecodeError, TypeError):
                pass
    return None


def _extract_messages_for_customer(customer_id: int, limit: int = 50) -> list[dict]:
    """从消息存储中提取客户消息列表。"""
    try:
        from app.services.message_store import get_messages
        msgs = get_messages(int(customer_id), limit=limit)
        return [
            {
                "content": m.content,
                "direction": m.direction,
                "created_at": m.created_at,
            }
            for m in msgs
        ]
    except Exception:
        logger.debug("提取客户 %s 消息失败", customer_id, exc_info=True)
        return []


# ── 公开 API ──────────────────────────────────────────────────────────────

def analyze_intent(message: str, context: str = "") -> dict[str, Any]:
    """分析消息意图。

    返回 {"intent": str, "confidence": float, "is_high_intent": bool, "keywords": list[str]}
    """
    if not message or not message.strip():
        return {"intent": "other", "confidence": 0.0, "is_high_intent": False, "keywords": []}

    provider_name, _ = _get_llm_client()

    # LLM 已配置时，调用 LLM 分析
    if provider_name:
        try:
            system_prompt = (
                "你是一个客户消息意图分类器。根据客户消息内容判断意图类别。\n"
                f"可选意图：{', '.join(f'{k}({v})' for k, v in INTENT_LABELS.items())}\n"
                '请严格以 JSON 格式返回：{"intent": "意图类别", "confidence": 0.0-1.0置信度, "keywords": ["关键词1", "关键词2"]}\n'
                "只返回 JSON，不要其他内容。"
            )
            user_prompt = f"客户消息：{message}"
            if context:
                user_prompt += f"\n上下文：{context}"

            raw = _call_llm(user_prompt, system_prompt=system_prompt, max_tokens=256)
            parsed = _parse_json_from_llm(raw)
            if isinstance(parsed, dict) and parsed.get("intent"):
                intent = str(parsed["intent"])
                if intent not in INTENT_TYPES:
                    intent = "other"
                confidence = float(parsed.get("confidence") or 0.5)
                confidence = max(0.0, min(1.0, confidence))
                keywords = parsed.get("keywords") or []
                if not isinstance(keywords, list):
                    keywords = []
                return {
                    "intent": intent,
                    "confidence": confidence,
                    "is_high_intent": intent in HIGH_INTENT_TYPES,
                    "keywords": keywords,
                }
        except Exception:
            logger.debug("LLM 意图分析失败，fallback 到关键词规则", exc_info=True)

    # LLM 未配置或调用失败时：关键词规则匹配
    intent, confidence, keywords = _keyword_match_intent(message)
    return {
        "intent": intent,
        "confidence": confidence,
        "is_high_intent": intent in HIGH_INTENT_TYPES,
        "keywords": keywords,
    }


def suggest_reply(
    customer_id: int,
    *,
    message: str = "",
    intent: str = "",
    stage: str = "",
    history: list[str] | None = None,
) -> list[dict[str, Any]]:
    """推荐回复话术，返回 2-3 条。

    每条格式：{"text": str, "style": str, "confidence": float}
    style: "professional" / "friendly" / "direct"
    """
    # 如果没有传入 intent，先分析
    if not intent and message:
        intent = analyze_intent(message).get("intent", "other")

    provider_name, _ = _get_llm_client()

    # LLM 已配置时，调用 LLM 生成话术
    if provider_name:
        try:
            stage_label = ""
            for s in PIPELINE_STAGES:
                if s["id"] == stage:
                    stage_label = s["label"]
                    break

            system_prompt = (
                "你是一个专业的销售跟单助手，根据客户消息和上下文推荐回复话术。\n"
                "请生成 2-3 条不同风格的回复话术，风格分为：professional（专业）、friendly（亲切）、direct（简洁）。\n"
                '请严格以 JSON 数组格式返回：[{"text": "话术内容", "style": "风格", "confidence": 0.0-1.0}]\n'
                "只返回 JSON 数组，不要其他内容。"
            )
            user_prompt_parts = []
            if message:
                user_prompt_parts.append(f"客户消息：{message}")
            if intent:
                intent_label = INTENT_LABELS.get(intent, intent)
                user_prompt_parts.append(f"客户意图：{intent_label}")
            if stage_label:
                user_prompt_parts.append(f"当前阶段：{stage_label}")
            if history:
                recent = history[-5:]
                user_prompt_parts.append(f"最近对话：{' | '.join(recent)}")

            raw = _call_llm("\n".join(user_prompt_parts), system_prompt=system_prompt, max_tokens=512)
            parsed = _parse_json_from_llm(raw)
            if isinstance(parsed, list) and len(parsed) >= 2:
                results: list[dict[str, Any]] = []
                for item in parsed[:3]:
                    if isinstance(item, dict) and item.get("text"):
                        results.append({
                            "text": str(item["text"]),
                            "style": str(item.get("style") or "professional"),
                            "confidence": float(item.get("confidence") or 0.7),
                        })
                if len(results) >= 2:
                    return results
        except Exception:
            logger.debug("LLM 话术推荐失败，fallback 到模板", exc_info=True)

    # LLM 未配置或调用失败时：返回模板话术
    templates = _TEMPLATE_REPLIES.get(intent, _TEMPLATE_REPLIES["default"])
    return templates[:3]


def generate_auto_reply(
    customer_id: int,
    *,
    message: str,
    intent: str = "",
    stage: str = "",
    history: list[str] | None = None,
) -> dict[str, Any]:
    """生成自动回复草稿。

    返回 {"draft": str, "can_auto_send": bool, "reason": str}
    can_auto_send=False 的场景：涉及价格承诺、合同条款、具体交付时间等
    """
    # 检测敏感关键词
    can_auto_send = True
    reason = ""
    for kw in _SENSITIVE_KEYWORDS:
        if kw in message:
            can_auto_send = False
            reason = f"消息涉及敏感内容「{kw}」，建议人工审核后发送"
            break

    # 如果没有传入 intent，先分析
    if not intent:
        intent = analyze_intent(message).get("intent", "other")

    provider_name, _ = _get_llm_client()

    # LLM 已配置时，调用 LLM 生成草稿
    if provider_name:
        try:
            stage_label = ""
            for s in PIPELINE_STAGES:
                if s["id"] == stage:
                    stage_label = s["label"]
                    break

            system_prompt = (
                "你是一个专业的销售跟单助手，请根据客户消息生成一条简洁专业的回复草稿。\n"
                "注意：不要做任何价格承诺、合同条款承诺或具体交付时间承诺。\n"
                "只返回回复文本，不要加引号或其他格式。"
            )
            user_prompt_parts = [f"客户消息：{message}"]
            if intent:
                intent_label = INTENT_LABELS.get(intent, intent)
                user_prompt_parts.append(f"客户意图：{intent_label}")
            if stage_label:
                user_prompt_parts.append(f"当前阶段：{stage_label}")
            if history:
                recent = history[-5:]
                user_prompt_parts.append(f"最近对话：{' | '.join(recent)}")

            draft = _call_llm("\n".join(user_prompt_parts), system_prompt=system_prompt, max_tokens=256)
            if draft:
                # 再次检查 LLM 生成的草稿中是否包含敏感内容
                for kw in _SENSITIVE_KEYWORDS:
                    if kw in draft:
                        can_auto_send = False
                        reason = f"AI 回复涉及敏感内容「{kw}」，建议人工审核"
                        break
                return {
                    "draft": draft,
                    "can_auto_send": can_auto_send,
                    "reason": reason,
                }
        except Exception:
            logger.debug("LLM 自动回复生成失败，fallback 到模板", exc_info=True)

    # LLM 未配置或调用失败时：使用模板
    templates = _TEMPLATE_REPLIES.get(intent, _TEMPLATE_REPLIES["default"])
    draft = templates[0]["text"]
    return {
        "draft": draft,
        "can_auto_send": can_auto_send,
        "reason": reason,
    }


def generate_customer_profile(customer_id: int, *, messages: list[dict] | None = None) -> dict[str, Any]:
    """生成客户画像。

    返回 {
        "needs_preference": str,   # 需求偏好
        "decision_role": str,      # 决策角色
        "budget_perception": str,  # 预算感知
        "urgency": str,            # 紧迫度 (high/medium/low)
        "summary": str,            # 一句话画像
        "tags": list[str],         # 推荐标签
    }
    """
    # 从 pipeline 获取客户信息
    try:
        doc = load_pipeline(int(customer_id))
    except Exception:
        logger.debug("加载客户 %s pipeline 失败", customer_id, exc_info=True)
        doc = {}

    stage = str(doc.get("stage") or "idle")
    stage_label = ""
    for s in PIPELINE_STAGES:
        if s["id"] == stage:
            stage_label = s["label"]
            break

    # 提取消息
    if messages is None:
        messages = _extract_messages_for_customer(customer_id, limit=30)

    # 构建消息摘要
    msg_texts = []
    for m in (messages or []):
        content = str(m.get("content") or "")
        direction = str(m.get("direction") or "")
        if content:
            prefix = "客户" if direction == "in" else "我方"
            msg_texts.append(f"{prefix}：{content[:100]}")

    msg_summary = "\n".join(msg_texts[-20:]) if msg_texts else "暂无消息记录"

    # 从 intake_form 提取信息
    intake = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}
    company = str(intake.get("company") or doc.get("erp_customer_name") or "")
    name = str(intake.get("name") or "")
    demand = str(intake.get("demand") or intake.get("requirement") or "")

    provider_name, _ = _get_llm_client()

    # LLM 已配置时，调用 LLM 生成画像
    if provider_name and msg_texts:
        try:
            system_prompt = (
                "你是一个客户画像分析专家，根据客户信息和对话记录生成客户画像。\n"
                '请严格以 JSON 格式返回：\n'
                '{\n'
                '  "needs_preference": "需求偏好描述",\n'
                '  "decision_role": "决策角色(决策者/影响者/使用者/未知)",\n'
                '  "budget_perception": "预算感知(高/中/低/未知)",\n'
                '  "urgency": "紧迫度(high/medium/low)",\n'
                '  "summary": "一句话客户画像",\n'
                '  "tags": ["标签1", "标签2"]\n'
                '}\n'
                "只返回 JSON，不要其他内容。"
            )
            user_prompt_parts = []
            if company:
                user_prompt_parts.append(f"公司：{company}")
            if name:
                user_prompt_parts.append(f"联系人：{name}")
            if demand:
                user_prompt_parts.append(f"需求：{demand}")
            user_prompt_parts.append(f"当前阶段：{stage_label or stage}")
            user_prompt_parts.append(f"对话记录：\n{msg_summary}")

            raw = _call_llm("\n".join(user_prompt_parts), system_prompt=system_prompt, max_tokens=512)
            parsed = _parse_json_from_llm(raw)
            if isinstance(parsed, dict) and parsed.get("summary"):
                return {
                    "needs_preference": str(parsed.get("needs_preference") or "未知"),
                    "decision_role": str(parsed.get("decision_role") or "未知"),
                    "budget_perception": str(parsed.get("budget_perception") or "未知"),
                    "urgency": str(parsed.get("urgency") or "medium"),
                    "summary": str(parsed.get("summary") or ""),
                    "tags": parsed.get("tags") if isinstance(parsed.get("tags"), list) else [],
                }
        except Exception:
            logger.debug("LLM 客户画像生成失败，fallback 到规则", exc_info=True)

    # LLM 未配置或调用失败时：基于规则生成简单画像
    urgency = "medium"
    if msg_texts:
        # 基于消息中的关键词判断紧迫度
        all_text = " ".join(msg_texts)
        if any(kw in all_text for kw in ["急", "催", "尽快", "马上", "加急"]):
            urgency = "high"
        elif any(kw in all_text for kw in ["不急", "慢慢", "以后再说", "暂时"]):
            urgency = "low"

    budget_perception = "未知"
    if msg_texts:
        all_text = " ".join(msg_texts)
        if any(kw in all_text for kw in ["太贵", "预算有限", "便宜", "优惠"]):
            budget_perception = "低"
        elif any(kw in all_text for kw in ["没问题", "可以接受", "不在乎"]):
            budget_perception = "高"

    tags: list[str] = []
    if company:
        tags.append("企业客户")
    if stage in ("negotiating", "quoted"):
        tags.append("价格敏感")
    if stage in ("contract_pending", "signed"):
        tags.append("高意向")
    if urgency == "high":
        tags.append("紧急跟进")

    summary_parts = []
    if company:
        summary_parts.append(company)
    if demand:
        summary_parts.append(f"需求：{demand[:30]}")
    summary_parts.append(f"阶段：{stage_label or stage}")
    summary = "，".join(summary_parts) if summary_parts else "暂无足够信息"

    return {
        "needs_preference": demand[:50] if demand else "未知",
        "decision_role": "未知",
        "budget_perception": budget_perception,
        "urgency": urgency,
        "summary": summary,
        "tags": tags,
    }


def get_follow_up_reminders(
    customer_ids: list[int] | None = None,
    *,
    hours_threshold: int = 48,
) -> list[dict[str, Any]]:
    """获取跟进提醒列表。

    返回 [{"customer_id": int, "display_name": str, "stage": str,
            "hours_since_last_contact": float, "suggested_action": str}]
    """
    results: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    # 获取客户列表
    if customer_ids:
        docs = []
        for cid in customer_ids:
            try:
                doc = load_pipeline(int(cid))
                docs.append(doc)
            except Exception:
                logger.debug("加载客户 %s pipeline 失败", cid, exc_info=True)
    else:
        docs = _iter_pipeline_docs()

    for doc in docs:
        uid = int(doc.get("customer_id") or doc.get("market_user_id") or 0)
        if uid <= 0:
            continue

        # 计算距上次更新的时间
        updated_at_str = str(doc.get("updated_at") or "")
        hours_since = float(hours_threshold + 1)  # 默认超过阈值

        if updated_at_str:
            try:
                updated_at = datetime.fromisoformat(updated_at_str)
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                delta = now - updated_at
                hours_since = delta.total_seconds() / 3600
            except (ValueError, TypeError):
                pass

        # 也检查最后消息时间
        messages = _extract_messages_for_customer(uid, limit=1)
        if messages:
            last_msg_at_str = str(messages[0].get("created_at") or "")
            if last_msg_at_str:
                try:
                    last_msg_at = datetime.fromisoformat(last_msg_at_str)
                    if last_msg_at.tzinfo is None:
                        last_msg_at = last_msg_at.replace(tzinfo=timezone.utc)
                    msg_hours = (now - last_msg_at).total_seconds() / 3600
                    # 取最近的活动时间
                    hours_since = min(hours_since, msg_hours)
                except (ValueError, TypeError):
                    pass

        pending_follow_up = bool(doc.get("pending_follow_up"))
        if hours_since < hours_threshold and not pending_follow_up:
            continue

        stage = str(doc.get("stage") or "idle")
        display_name = _display_name_from_doc(doc)

        # 根据阶段生成建议动作
        suggested_action = str(doc.get("next_action") or "").strip() or _suggest_action_by_stage(stage, hours_since)

        results.append({
            "customer_id": uid,
            "display_name": display_name,
            "stage": stage,
            "hours_since_last_contact": round(hours_since, 1),
            "suggested_action": suggested_action,
            "pending_follow_up": pending_follow_up,
            "reason": str(doc.get("follow_up_reason") or ""),
        })

    # 先排新消息待处理，再按失联时长排序
    results.sort(key=lambda r: (not bool(r.get("pending_follow_up")), -float(r["hours_since_last_contact"])))
    return results


def _suggest_action_by_stage(stage: str, hours_since: float) -> str:
    """根据阶段和失联时长建议跟进动作。"""
    stage_actions: dict[str, str] = {
        "idle": "主动建联，发送欢迎语",
        "connected": "发送需求采集表单，了解客户需求",
        "intake": "跟进需求采集进度",
        "intake_done": "准备报价方案",
        "quoted": "跟进报价反馈，了解客户意向",
        "negotiation": "主动沟通价格方案，推进成交",
        "contract_pending": "跟进合同签署进度",
        "signed": "确认交付安排",
        "delivering": "跟进交付进度",
        "delivered": "回访客户满意度，挖掘二次需求",
    }
    action = stage_actions.get(stage, "主动跟进客户")

    if hours_since > 168:  # 超过 7 天
        action += "（已超7天未联系，建议尽快跟进）"
    elif hours_since > 72:  # 超过 3 天
        action += "（已超3天未联系）"

    return action


def calculate_ai_score(customer_id: int, *, messages: list[dict] | None = None) -> float:
    """计算客户 AI 意向度评分（0-1）。

    基于因素：消息频率(30%) + 高意向消息占比(30%) + 阶段进度(20%) + 响应速度(20%)
    """
    # 从 pipeline 获取阶段信息
    try:
        doc = load_pipeline(int(customer_id))
    except Exception:
        logger.debug("加载客户 %s pipeline 失败", customer_id, exc_info=True)
        return 0.0

    stage = str(doc.get("stage") or "idle")

    # 提取消息
    if messages is None:
        messages = _extract_messages_for_customer(customer_id, limit=50)

    if not messages:
        # 没有消息时仅基于阶段评分
        stage_score = _stage_rank(stage) / max(len(_STAGE_ORDER) - 1, 1)
        return round(stage_score * 0.2, 2)

    # ── 1. 消息频率得分 (30%) ──
    # 近 7 天的消息数量
    now = datetime.now(timezone.utc)
    recent_count = 0
    for m in messages:
        created_at_str = str(m.get("created_at") or "")
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if (now - created_at).days <= 7:
                    recent_count += 1
            except (ValueError, TypeError):
                recent_count += 1  # 无法解析时算入
        else:
            recent_count += 1

    # 频率得分：1-3 条 0.3，4-10 条 0.6，11-20 条 0.8，20+ 条 1.0
    if recent_count <= 0:
        freq_score = 0.0
    elif recent_count <= 3:
        freq_score = 0.3
    elif recent_count <= 10:
        freq_score = 0.6
    elif recent_count <= 20:
        freq_score = 0.8
    else:
        freq_score = 1.0

    # ── 2. 高意向消息占比得分 (30%) ──
    inbound_messages = [
        m for m in messages
        if str(m.get("direction") or "").lower() in {"in", "inbound", "incoming", "customer"}
    ]
    high_intent_count = 0
    for m in inbound_messages:
        content = str(m.get("content") or "")
        if content:
            intent_result = analyze_intent(content)
            if intent_result.get("is_high_intent"):
                high_intent_count += 1

    total_inbound = max(len(inbound_messages), 1)
    high_intent_ratio = high_intent_count / total_inbound
    high_intent_score = min(high_intent_ratio * 2, 1.0)  # 50% 高意向即满分

    # ── 3. 阶段进度得分 (20%) ──
    stage_score = _stage_rank(stage) / max(len(_STAGE_ORDER) - 1, 1)

    # ── 4. 响应速度得分 (20%) ──
    # 计算客户消息之间的平均间隔（越小越积极）
    response_score = 0.5  # 默认中等
    inbound_times: list[datetime] = []
    for m in inbound_messages:
        created_at_str = str(m.get("created_at") or "")
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                inbound_times.append(created_at)
            except (ValueError, TypeError):
                pass

    if len(inbound_times) >= 2:
        inbound_times.sort()
        intervals = []
        for i in range(1, len(inbound_times)):
            delta = (inbound_times[i] - inbound_times[i - 1]).total_seconds() / 3600
            if delta > 0:
                intervals.append(delta)
        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            # 平均间隔 < 1h → 1.0, 1-6h → 0.8, 6-24h → 0.6, 24-72h → 0.4, >72h → 0.2
            if avg_interval <= 1:
                response_score = 1.0
            elif avg_interval <= 6:
                response_score = 0.8
            elif avg_interval <= 24:
                response_score = 0.6
            elif avg_interval <= 72:
                response_score = 0.4
            else:
                response_score = 0.2

    # ── 加权计算总分 ──
    total_score = (
        freq_score * 0.30
        + high_intent_score * 0.30
        + stage_score * 0.20
        + response_score * 0.20
    )

    return round(max(0.0, min(1.0, total_score)), 2)


__all__ = [
    "INTENT_TYPES",
    "INTENT_LABELS",
    "HIGH_INTENT_TYPES",
    "analyze_intent",
    "suggest_reply",
    "generate_auto_reply",
    "generate_customer_profile",
    "get_follow_up_reminders",
    "calculate_ai_score",
]
