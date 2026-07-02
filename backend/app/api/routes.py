"""客来来 HTTP API（自 xcagi-customer-service-bridge user-cs 路由复制 · 独立前缀）。"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.auth_middleware import CurrentUser
from app.services.rate_limiter import check_llm_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kellai", tags=["kellai"])

# --- 路径白名单（无需认证保护）---
AUTH_WHITELIST: set[str] = {
    "/health",
    "/api/kellai/status",
    "/api/kellai/landing/sync",
    "/api/kellai/webhook/wework",
    "/api/kellai/channels/wework/oauth/callback",
}


def get_request_user(request: Request) -> Optional[dict]:
    """从 request.state.user 读取中间件解析的当前用户"""
    return getattr(request.state, "user", None)


OptionalUser = Annotated[Optional[dict], Depends(get_request_user)]


def enforce_llm_rate_limit(request: Request) -> None:
    """LLM 端点限流依赖：超出返回 429"""
    user = get_request_user(request)
    user_key = "anonymous"
    if user and "id" in user:
        user_key = f"user:{user['id']}"
    else:
        # 软认证：未登录用户用 IP 作为 key
        client = request.client
        user_key = f"ip:{client.host if client else 'unknown'}"
    allowed, retry_after = check_llm_rate_limit(user_key)
    if not allowed:
        logger.warning("LLM 限流触发: key=%s, retry_after=%.1fs", user_key, retry_after)
        raise HTTPException(
            status_code=429,
            detail={"message": "请求过于频繁，请稍后再试", "retry_after": round(retry_after, 1)},
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


def _cid(body: Any = None, **kwargs: Any) -> int:
    if body is not None:
        raw = getattr(body, "customer_id", None) or getattr(body, "market_user_id", None)
        if raw:
            return int(raw)
    for key in ("customer_id", "market_user_id"):
        if key in kwargs and kwargs[key]:
            return int(kwargs[key])
    return 0


class PipelineBody(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    market_user_id: Optional[int] = Field(default=None, gt=0)
    username: str = Field(default="", max_length=128)
    stage: Optional[str] = Field(default=None, max_length=32)
    intake_sent: bool = False
    manual: bool = True
    note: str = Field(default="", max_length=200)


class AnalyzeBody(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    market_user_id: Optional[int] = Field(default=None, gt=0)
    username: str = Field(default="", max_length=128)
    has_binding: bool = False
    intake_sent: bool = False


class LandingSyncBody(BaseModel):
    customer_id: Optional[int] = Field(default=None)
    market_user_id: Optional[int] = Field(default=None)
    landing_contact_id: Optional[int] = None
    name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    company: str = Field(default="", max_length=256)
    message: str = Field(default="", max_length=8000)
    desktop_os: str = Field(default="", max_length=16)
    need_mobile: bool = Field(default=True)
    submitted_at: str = Field(default="", max_length=64)


class WechatSendBody(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    market_user_id: Optional[int] = Field(default=None, gt=0)
    contact_name: str = Field(..., min_length=1, max_length=256)
    message: str = Field(..., min_length=1, max_length=8000)
    username: str = Field(default="", max_length=128)


class WelcomeBody(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    market_user_id: Optional[int] = Field(default=None, gt=0)
    username: str = Field(default="", max_length=128)
    contact_name: str = Field(default="", max_length=256)
    force: bool = False


class IntakeNoticeBody(WelcomeBody):
    brief: str = Field(default="", max_length=4000)


class PassivePollBody(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    market_user_id: Optional[int] = Field(default=None, gt=0)
    username: str = Field(default="", max_length=128)
    dry_run: bool = True
    auto_reply: bool = True
    max_replies: int = Field(default=0, ge=0, le=5)
    use_llm: bool = True
    skip_sync: bool = False


class PassiveLoopBody(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    market_user_id: Optional[int] = Field(default=None, gt=0)
    username: str = Field(default="", max_length=128)
    poll_enabled: bool = False
    poll_interval_sec: int = Field(default=60, ge=10, le=600)


class BindingsBody(BaseModel):
    contact_ids: list[int] = Field(default_factory=list)


class ChannelSendMessageBody(BaseModel):
    customer_id: int = Field(..., gt=0)
    channel_type: str = Field(..., min_length=1, max_length=32)
    contact_id: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1, max_length=8000)


class MarkReadBody(BaseModel):
    """标记已读 body。message_ids 优先；不传则按 customer_id 标记；都不传则全量。"""
    message_ids: list[str] = Field(default_factory=list, max_length=500)
    customer_id: Optional[int] = Field(default=None, gt=0)
    all: bool = False


class ChannelSyncInboxBody(BaseModel):
    """同步渠道收件箱到客户消息与漏斗闭环。"""
    channel_type: str = Field(default="", max_length=32)
    limit: int = Field(default=50, ge=1, le=200)


class SimulateCustomerBehaviorBody(BaseModel):
    """演示用：模拟真实客户进线行为。"""
    count: int = Field(default=5, ge=1, le=20)
    scenario_set: str = Field(default="realistic", max_length=32)


class TtsSpeakBody(BaseModel):
    """云端语音播报（优先 MiMo TTS）。"""
    text: str = Field(..., min_length=1, max_length=1200)
    voice: str = Field(default="", max_length=80)
    rate: int = Field(default=185, ge=120, le=260)


class LLMFullFlowTestBody(BaseModel):
    """LLM/脚本驱动：多轮客户行为 + 销售回复 + 漏斗断言。"""
    turns: int = Field(default=5, ge=1, le=8)
    target_stage: str = Field(default="signed", max_length=32)
    channel_type: str = Field(default="douyin", max_length=32)
    scenario: str = Field(default="", max_length=64)
    use_llm: bool = True
    auto_reply: bool = True
    require_llm: bool = True


class ClosedLoopAuditBody(BaseModel):
    """产品闭环验收：核心链路 + 可选真实 LLM 强校验。"""
    require_llm: bool = True
    target_stage: str = Field(default="signed", max_length=32)


class LLMConfigBody(BaseModel):
    """设置页保存的真实 LLM 配置。api_key 为空时保留原 Key。"""
    provider: str = Field(default="deepseek", max_length=32)
    model: str = Field(default="", max_length=128)
    base_url: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=4096)
    auto_reply_enabled: bool = False
    auto_reply_stages: list[str] = Field(default_factory=list, max_length=20)
    confirm_scenarios: list[str] = Field(default_factory=list, max_length=20)


class KnowledgeArticleBody(BaseModel):
    id: str = Field(default="", max_length=80)
    title: str = Field(..., min_length=1, max_length=160)
    content: str = Field(..., min_length=1, max_length=12000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    source: str = Field(default="manual", max_length=80)


class KnowledgeQueryBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    customer_id: Optional[int] = Field(default=None, gt=0)
    limit: int = Field(default=5, ge=1, le=20)


class ServiceTicketCreateBody(BaseModel):
    customer_id: int = Field(..., gt=0)
    title: str = Field(default="高风险会话转人工", max_length=160)
    reason: str = Field(default="", max_length=1000)
    assignee: str = Field(default="", max_length=80)
    priority: str = Field(default="high", max_length=32)
    source: str = Field(default="manual", max_length=80)
    sla_minutes: int = Field(default=30, ge=5, le=1440)
    from_quality: bool = True


class ServiceTicketAssignBody(BaseModel):
    assignee: str = Field(..., min_length=1, max_length=80)
    actor: str = Field(default="system", max_length=80)


class ServiceTicketResolveBody(BaseModel):
    resolution: str = Field(..., min_length=1, max_length=1000)
    actor: str = Field(default="system", max_length=80)
    rehost_to_ai: bool = True


class ServiceLearningBody(BaseModel):
    persist: bool = True


class OutboundCallPlanBody(BaseModel):
    customer_id: int = Field(..., gt=0)
    purpose: str = Field(default="follow_up", max_length=64)
    assignee: str = Field(default="AI外呼助手", max_length=80)


class OutboundCallExecuteBody(BaseModel):
    outcome: str = Field(default="demo_booked", max_length=64)
    note: str = Field(default="", max_length=500)
    actor: str = Field(default="desktop", max_length=80)


class SelfServiceResolutionBody(BaseModel):
    query: str = Field(default="", max_length=2000)
    channel_type: str = Field(default="", max_length=32)
    fallback_to_ticket: bool = True


class AgentAssistBody(BaseModel):
    persist: bool = True
    actor: str = Field(default="desktop", max_length=80)


# ---------------------------------------------------------------------------
# 认证与团队 Body 模型
# ---------------------------------------------------------------------------


class RegisterBody(BaseModel):
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=128)
    name: str = Field(default="", max_length=128)


class LoginBody(BaseModel):
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=128)
    code: str = Field(default="", max_length=6)


class RefreshBody(BaseModel):
    refresh_token: str = Field(..., min_length=1, max_length=512)


class ResetPasswordBody(BaseModel):
    phone: str = Field(..., min_length=1, max_length=64)
    code: str = Field(..., min_length=4, max_length=6)
    new_password: str = Field(..., min_length=1, max_length=128)


class UpdateUserBody(BaseModel):
    display_name: str = Field(default="", max_length=128)
    avatar_url: str = Field(default="", max_length=512)


class InviteBody(BaseModel):
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    role: str = Field(default="sales", max_length=32)


class RoleBody(BaseModel):
    role: str = Field(..., max_length=32)


class JoinBody(BaseModel):
    invite_code: str = Field(..., min_length=1, max_length=64)


# ---- AI 跟单助手 ----

class IntentBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    context: str = Field(default="", max_length=2000)


class SuggestReplyBody(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    market_user_id: Optional[int] = Field(default=None, gt=0)
    message: str = Field(default="", max_length=5000)
    intent: str = Field(default="", max_length=32)
    stage: str = Field(default="", max_length=32)


class AutoReplyBody(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    market_user_id: Optional[int] = Field(default=None, gt=0)
    message: str = Field(..., min_length=1, max_length=5000)
    intent: str = Field(default="", max_length=32)
    stage: str = Field(default="", max_length=32)


class ScoreBody(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    market_user_id: Optional[int] = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# 渠道统一 API
# ---------------------------------------------------------------------------


CHANNEL_ONBOARDING_GUIDES: dict[str, dict[str, Any]] = {
    "wework": {
        "recommended_mode": "scan",
        "auth_modes": ["scan", "form"],
        "required_fields": ["corp_id", "secret", "agent_id"],
        "optional_fields": ["bot_webhook", "kf_url", "open_kfid"],
        "materials": ["企业微信管理员权限", "自建应用的 Corp ID / Agent ID / Secret", "企业微信客服链接或 open_kfid"],
        "external_steps": ["在企业微信后台创建或选择自建应用", "配置可信域名和回调地址", "把 Corp ID、Agent ID、Secret 回填到客来来", "扫码授权并测试连接"],
        "success_criteria": ["测试连接通过", "能同步一条企微客户消息", "客户自动进入漏斗并生成下一步动作"],
    },
    "douyin": {
        "recommended_mode": "scan",
        "auth_modes": ["scan", "form"],
        "required_fields": ["app_id", "app_secret"],
        "optional_fields": ["client_key", "client_secret"],
        "materials": ["抖音开放平台应用", "App ID / App Secret", "商家账号或客服权限"],
        "external_steps": ["在抖音开放平台创建应用", "开通客服消息或私信相关权限", "把应用凭据回填到客来来", "测试连接后同步收件箱"],
        "success_criteria": ["测试连接通过", "抖音进线能入库", "客户阶段随消息自动推进"],
    },
    "miniprogram": {
        "recommended_mode": "scan",
        "auth_modes": ["scan", "form"],
        "required_fields": ["app_id", "app_secret"],
        "optional_fields": ["template_id"],
        "materials": ["公众号或小程序管理员权限", "App ID / App Secret", "模板消息 ID（可选）"],
        "external_steps": ["在微信公众平台确认开发者配置", "配置服务器域名和消息回调", "把 App ID / Secret 回填到客来来", "测试连接并同步留资消息"],
        "success_criteria": ["测试连接通过", "小程序留资能入库", "消息能关联到客户档案"],
    },
    "pdd": {
        "recommended_mode": "scan",
        "auth_modes": ["scan", "form"],
        "required_fields": ["client_id", "client_secret"],
        "optional_fields": [],
        "materials": ["拼多多开放平台应用", "Client ID / Client Secret", "商家工作台授权账号"],
        "external_steps": ["创建或选择拼多多开放平台应用", "申请客服/订单相关接口权限", "回填 Client ID / Secret", "测试连接并同步消息"],
        "success_criteria": ["测试连接通过", "店铺客户消息能进入消息中心"],
    },
    "taobao": {
        "recommended_mode": "scan",
        "auth_modes": ["scan", "form"],
        "required_fields": ["app_key", "app_secret"],
        "optional_fields": [],
        "materials": ["淘宝开放平台应用", "App Key / App Secret", "千牛商家账号"],
        "external_steps": ["在淘宝开放平台创建应用", "申请客服消息权限", "回填 App Key / Secret", "测试连接并同步消息"],
        "success_criteria": ["测试连接通过", "千牛消息能进入统一收件箱"],
    },
    "jd": {
        "recommended_mode": "scan",
        "auth_modes": ["scan", "form"],
        "required_fields": ["app_key", "app_secret"],
        "optional_fields": [],
        "materials": ["京东宙斯/开放平台应用", "App Key / App Secret", "京麦商家账号"],
        "external_steps": ["创建京东开放平台应用", "申请客服或订单相关权限", "回填 App Key / Secret", "测试连接并同步消息"],
        "success_criteria": ["测试连接通过", "京东客户消息能进入统一收件箱"],
    },
    "alibaba": {
        "recommended_mode": "scan",
        "auth_modes": ["scan", "form"],
        "required_fields": ["app_key", "app_secret"],
        "optional_fields": [],
        "materials": ["1688/阿里开放平台应用", "App Key / App Secret", "商家账号授权"],
        "external_steps": ["创建阿里开放平台应用", "申请买家咨询相关权限", "回填 App Key / Secret", "测试连接并同步消息"],
        "success_criteria": ["测试连接通过", "1688 客户咨询能入库"],
    },
    "whatsapp": {
        "recommended_mode": "form",
        "auth_modes": ["form"],
        "required_fields": ["phone_number_id", "access_token"],
        "optional_fields": ["business_id"],
        "materials": ["WhatsApp Business 账号", "Phone Number ID", "长期 Access Token"],
        "external_steps": ["在 Meta Business 后台准备号码和 Token", "配置 Webhook 回调", "回填 Phone Number ID / Token", "测试连接"],
        "success_criteria": ["测试连接通过", "WhatsApp 消息能同步到客来来"],
    },
    "telegram": {
        "recommended_mode": "form",
        "auth_modes": ["form"],
        "required_fields": ["bot_token"],
        "optional_fields": [],
        "materials": ["Telegram Bot", "Bot Token"],
        "external_steps": ["通过 BotFather 创建 Bot", "复制 Bot Token", "回填并测试连接"],
        "success_criteria": ["测试连接通过", "Bot 消息能同步到客来来"],
    },
    "line": {
        "recommended_mode": "form",
        "auth_modes": ["form"],
        "required_fields": ["channel_access_token"],
        "optional_fields": ["channel_secret"],
        "materials": ["LINE Official Account", "Channel Access Token", "Channel Secret（可选）"],
        "external_steps": ["在 LINE Developers 建立 Messaging API Channel", "启用 Webhook", "回填 Token / Secret", "测试连接"],
        "success_criteria": ["测试连接通过", "LINE 消息能进入统一收件箱"],
    },
    "phone": {
        "recommended_mode": "select",
        "auth_modes": ["select"],
        "required_fields": ["line"],
        "optional_fields": [],
        "materials": ["可用外呼线路"],
        "external_steps": ["选择外呼线路", "保存后测试外呼线路", "后续由 AI 外呼任务调用"],
        "success_criteria": ["测试连接通过", "外呼记录能回写客户时间线"],
    },
    "email": {
        "recommended_mode": "none",
        "auth_modes": ["none"],
        "required_fields": [],
        "optional_fields": [],
        "materials": [],
        "external_steps": ["当前版本无需额外配置，可直接作为客户来源"],
        "success_criteria": ["渠道展示为可用"],
    },
    "sms": {
        "recommended_mode": "none",
        "auth_modes": ["none"],
        "required_fields": [],
        "optional_fields": [],
        "materials": ["短信服务商账号（后续生产接入时配置）"],
        "external_steps": ["当前版本先保留入口，生产接入时再配置服务商 Key"],
        "success_criteria": ["渠道入口可见"],
    },
    "web": {
        "recommended_mode": "none",
        "auth_modes": ["none"],
        "required_fields": [],
        "optional_fields": [],
        "materials": ["网站表单或落地页入口"],
        "external_steps": ["当前版本用于承接网页线索来源，无需额外配置"],
        "success_criteria": ["网页线索能进入客户列表"],
    },
}


def _channel_onboarding_profile(
    channel_type: str,
    config: dict[str, Any],
    *,
    connected: bool,
    enabled: bool,
) -> dict[str, Any]:
    guide = CHANNEL_ONBOARDING_GUIDES.get(channel_type, {})
    required_fields = [str(x) for x in guide.get("required_fields", [])]
    optional_fields = [str(x) for x in guide.get("optional_fields", [])]
    missing_required = [key for key in required_fields if not str(config.get(key) or "").strip()]
    saved_fields = [key for key, value in config.items() if str(value or "").strip()]
    required_complete = not missing_required
    if connected:
        status = "connected"
        next_action = "同步收件箱，确认客户消息能进入漏斗。"
    elif saved_fields:
        status = "saved"
        next_action = "补齐必填字段并保存后，再测试连接。" if missing_required else "点击测试连接，确认平台凭据可用。"
    elif guide.get("recommended_mode") == "none":
        status = "ready"
        next_action = "无需配置，可在客户来源中直接使用。"
    else:
        status = "not_started"
        next_action = "先准备平台材料，然后按向导授权或回填字段。"

    stages = [
        {"key": "prepare", "label": "准备材料", "status": "done" if saved_fields or connected or not required_fields else "current"},
        {
            "key": "configure",
            "label": "授权/配置",
            "status": (
                "done"
                if connected or (saved_fields and required_complete)
                else ("current" if saved_fields and missing_required else ("skipped" if not required_fields else "pending"))
            ),
        },
        {"key": "test", "label": "测试连接", "status": "done" if connected else ("current" if saved_fields and required_complete else "pending")},
        {"key": "sync", "label": "同步收件箱", "status": "current" if connected else "pending"},
    ]
    return {
        "status": status,
        "recommended_mode": str(guide.get("recommended_mode") or "form"),
        "auth_modes": list(guide.get("auth_modes") or ["form"]),
        "required_fields": required_fields,
        "optional_fields": optional_fields,
        "missing_required_fields": missing_required,
        "saved_fields": saved_fields,
        "materials": list(guide.get("materials") or []),
        "external_steps": list(guide.get("external_steps") or []),
        "success_criteria": list(guide.get("success_criteria") or []),
        "stages": stages,
        "next_action": next_action,
        "can_scan": "scan" in (guide.get("auth_modes") or []),
        "can_manual": bool(required_fields or optional_fields),
        "enabled": enabled,
    }


@router.get("/channels")
async def list_channels():
    """列出所有已注册渠道及状态（含已保存的配置）。"""
    from app.channels import ChannelRegistry
    from app.channels.config_store import get_all

    reg = ChannelRegistry()
    channels = reg.list_channels()
    result = []
    for ch in channels:
        cfg = get_all(ch["channel_type"])
        merged_config = dict(cfg.get("config") or {})
        has_config = any(str(v).strip() for v in merged_config.values())
        enabled = bool(cfg.get("enabled", has_config))
        connected = enabled and bool(cfg.get("connected"))
        result.append({
            "id": f"ch_{ch['channel_type']}",
            "name": cfg.get("name") or ch["channel_type"],
            "type": ch["channel_type"],
            "adapter_class": ch["adapter_class"],
            "enabled": enabled,
            "connected": connected,
            "message": "已连接" if connected else ("已保存配置，点击测试连接验证" if has_config else "未配置"),
            "config": merged_config,
            "config_schema": ch.get("config_schema") or {},
            "onboarding": _channel_onboarding_profile(
                ch["channel_type"],
                merged_config,
                connected=connected,
                enabled=enabled,
            ),
            "createdAt": cfg.get("createdAt") or "",
        })
    return {"success": True, "data": result}


@router.post("/channels/{channel_type}/test")
async def test_channel(channel_type: str):
    """测试指定渠道连接。"""
    from app.channels import ChannelRegistry
    from app.channels.config_store import get as get_config
    from app.channels.config_store import save as save_config

    reg = ChannelRegistry()
    try:
        adapter = reg.get(channel_type)
    except KeyError:
        return {"success": False, "error": f"未注册的渠道类型: {channel_type}"}
    try:
        result = await adapter.test_connection()
    except Exception as exc:
        return {"success": False, "error": f"测试失败: {exc}"}
    connected = bool(result.get("connected"))
    try:
        existing = get_config(channel_type)
        if connected:
            save_config(channel_type, {}, enabled=True, connected=True)
        elif existing:
            save_config(channel_type, {}, connected=False)
    except Exception as exc:
        logger.warning("保存渠道连接测试状态失败: %s", exc)
    return {
        "success": connected,
        "data": result,
        "message": result.get("message", ""),
    }


class ChannelConfigUpdate(BaseModel):
    """渠道配置更新请求体。"""
    config: dict[str, str] = Field(default_factory=dict)
    name: Optional[str] = None
    enabled: Optional[bool] = None


@router.put("/channels/{channel_type}/config")
async def update_channel_config(channel_type: str, body: ChannelConfigUpdate):
    """保存渠道配置。"""
    from app.channels import ChannelRegistry
    from app.channels.config_store import save as save_config

    reg = ChannelRegistry()
    try:
        reg.get(channel_type)  # 校验渠道存在
    except KeyError:
        raise HTTPException(status_code=404, detail={"message": f"未注册的渠道类型: {channel_type}"})

    saved = save_config(
        channel_type,
        body.config,
        name=body.name,
        enabled=body.enabled,
        connected=False,
    )
    logger.info("渠道配置已保存: %s (enabled=%s)", channel_type, saved.get("enabled"))
    return {
        "success": True,
        "data": {
            "id": f"ch_{channel_type}",
            "name": saved.get("name", channel_type),
            "type": channel_type,
            "enabled": bool(saved.get("enabled")),
            "connected": bool(saved.get("connected")),
            "config": saved.get("config", {}),
            "onboarding": _channel_onboarding_profile(
                channel_type,
                dict(saved.get("config") or {}),
                connected=bool(saved.get("enabled")) and bool(saved.get("connected")),
                enabled=bool(saved.get("enabled")),
            ),
        },
    }


@router.delete("/channels/{channel_type}")
async def delete_channel(channel_type: str):
    """断开 / 删除渠道配置。"""
    from app.channels import ChannelRegistry
    from app.channels.config_store import delete as delete_config

    reg = ChannelRegistry()
    try:
        reg.get(channel_type)
    except KeyError:
        raise HTTPException(status_code=404, detail={"message": f"未注册的渠道类型: {channel_type}"})

    deleted = delete_config(channel_type)
    return {"success": True, "data": {"type": channel_type, "deleted": deleted}}


@router.post("/channels/sync-inbox")
async def sync_channel_inbox(body: ChannelSyncInboxBody):
    """消费渠道收件箱，落库为客户消息，并驱动客户/漏斗/待办闭环。"""
    from app.channels import ChannelRegistry
    from app.services.message_store import mark_inbox_consumed, save_message

    reg = ChannelRegistry()
    if body.channel_type.strip():
        channel_types = [body.channel_type.strip()]
    else:
        channel_types = [c["channel_type"] for c in reg.list_channels()]

    saved_messages: list[dict[str, Any]] = []
    consumed_ids: list[str] = []
    seen_ids: set[str] = set()
    errors: list[dict[str, str]] = []

    for channel_type in channel_types:
        try:
            adapter = reg.get(channel_type)
        except KeyError as exc:
            errors.append({"channel_type": channel_type, "error": str(exc)})
            continue
        try:
            messages = await adapter.receive_messages(limit=body.limit)
        except Exception as exc:
            logger.warning("同步渠道收件箱失败: channel=%s", channel_type, exc_info=True)
            errors.append({"channel_type": channel_type, "error": str(exc)})
            continue
        for msg in messages:
            if msg.id in seen_ids:
                continue
            seen_ids.add(msg.id)
            saved = save_message(msg)
            consumed_ids.append(msg.id)
            saved_messages.append(saved.model_dump())

    consumed = mark_inbox_consumed(consumed_ids)
    return {
        "success": True,
        "data": {
            "synced": len(saved_messages),
            "consumed": consumed,
            "messages": saved_messages,
            "errors": errors,
        },
    }


# ---------------------------------------------------------------------------
# 企微 OAuth 端点
# ---------------------------------------------------------------------------

_oauth_states: dict[str, float] = {}  # state → 过期时间戳


@router.post("/channels/wework/oauth/initiate")
async def wework_oauth_initiate(request: Request):
    """发起企微 OAuth 授权，返回扫码授权 URL。"""
    import os
    import secrets
    import time

    from app.channels.config_store import get_field

    corp_id = get_field("wework", "corp_id") or os.environ.get("WW_CORP_ID", "")
    agent_id = get_field("wework", "agent_id") or os.environ.get("WW_AGENT_ID", "")

    if not corp_id or not agent_id:
        return {"success": False, "error": "请先配置 Corp ID 和 Agent ID"}

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = time.time() + 300  # 5 分钟过期

    redirect_uri = str(request.base_url).rstrip("/") + "/api/kellai/channels/wework/oauth/callback"
    from urllib.parse import quote_plus
    encoded_redirect = quote_plus(redirect_uri)

    url = (
        f"https://open.work.weixin.qq.com/wwopen/sso/qrConnect"
        f"?appid={corp_id}&agentid={agent_id}"
        f"&redirect_uri={encoded_redirect}&state={state}"
    )

    return {"success": True, "data": {"url": url, "state": state, "expires_in": 300}}


@router.get("/channels/wework/oauth/callback")
async def wework_oauth_callback(code: str = "", state: str = ""):
    """企微 OAuth 回调：用 code 换取用户信息并保存。"""
    import os
    import time

    from fastapi.responses import HTMLResponse

    from app.channels.config_store import get_field, save

    # 验证 state
    if not state or state not in _oauth_states:
        return HTMLResponse(
            "<html><body><h3>授权失败：无效的 state 参数</h3></body></html>",
            status_code=400,
        )

    expire_at = _oauth_states.pop(state)
    if time.time() > expire_at:
        return HTMLResponse(
            "<html><body><h3>授权失败：state 已过期，请重新发起授权</h3></body></html>",
            status_code=400,
        )

    if not code:
        return HTMLResponse(
            "<html><body><h3>授权失败：未收到授权码</h3></body></html>",
            status_code=400,
        )

    # 用 code 换取 access_token / 用户信息
    corp_id = get_field("wework", "corp_id") or os.environ.get("WW_CORP_ID", "")
    corp_secret = (
        get_field("wework", "secret")
        or get_field("wework", "corp_secret")
        or os.environ.get("WW_CORP_SECRET", "")
    )

    import httpx

    user_info: dict = {}
    try:
        # 1) 获取 access_token
        token_url = (
            f"https://qyapi.weixin.qq.com/cgi-bin/gettoken"
            f"?corpid={corp_id}&corpsecret={corp_secret}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.get(token_url)
            token_data = token_resp.json()

        access_token = token_data.get("access_token", "")
        if not access_token:
            logger.warning("企微 OAuth 获取 access_token 失败: %s", token_data)
        else:
            # 2) 用 code 换取用户身份
            user_url = (
                f"https://qyapi.weixin.qq.com/cgi-bin/auth/getuserinfo"
                f"?access_token={access_token}&code={code}"
            )
            async with httpx.AsyncClient(timeout=10) as client:
                user_resp = await client.get(user_url)
                user_info = user_resp.json()
    except Exception as exc:
        logger.warning("企微 OAuth 回调请求失败: %s", exc)

    # 保存授权信息到 config_store
    save("wework", {
        "oauth_authorized": "true",
        "oauth_user_id": user_info.get("userid", user_info.get("UserId", "")),
        "oauth_user_ticket": user_info.get("user_ticket", ""),
    })

    return HTMLResponse(
        "<html><body>"
        "<h3>授权成功，请返回客来来应用</h3>"
        "<script>window.close();</script>"
        "</body></html>"
    )


@router.get("/channels/wework/oauth/status")
async def wework_oauth_status(state: str = ""):
    """查询 OAuth 授权状态（前端轮询）。"""
    import time

    if not state:
        return {"success": True, "data": {"authorized": False, "expired": True}}

    if state not in _oauth_states:
        # state 已被 callback 消费，说明授权成功
        return {"success": True, "data": {"authorized": True}}

    expire_at = _oauth_states[state]
    if time.time() > expire_at:
        return {"success": True, "data": {"authorized": False, "expired": True}}

    return {"success": True, "data": {"authorized": False}}


@router.get("/messages")
def get_messages(
    request: Request,
    current_user: CurrentUser,
    customer_id: int | None = None,
    channel_type: str = "",
    limit: int = 50,
    since: str = "",
):
    """获取消息列表。
    
    当 customer_id 缺省时，按团队所有客户的消息返回。
    """
    from app.services.message_store import get_messages_with_state as _get_messages
    from app.services.pipeline import list_pipeline_client_summaries

    if customer_id:
        # 指定了客户 ID，直接查询该客户的消息
        messages = _get_messages(customer_id=int(customer_id), channel_type=channel_type, limit=limit, since=since)
    else:
        # 未指定 customer_id：获取当前用户团队的所有客户消息
        team_id = current_user.get("team_id")
        all_clients = list_pipeline_client_summaries()
        # 如果没有 team_id，返回所有客户消息（兼容模式）
        if team_id:
            # 只保留属于本团队的客户
            team_customer_ids = {c["customer_id"] for c in all_clients}
        else:
            team_customer_ids = {c["customer_id"] for c in all_clients}

        messages = []
        for cid in sorted(team_customer_ids, reverse=True)[:50]:  # 限制查询的客户数
            msgs = _get_messages(customer_id=cid, channel_type=channel_type, limit=limit, since=since)
            messages.extend(msgs)

        # 按时间倒序并截断
        messages.sort(key=lambda m: str(m.get("created_at") or ""), reverse=True)
        messages = messages[:limit]

    return {
        "success": True,
        "data": messages,
        "total": len(messages),
    }


@router.post("/messages/send")
async def send_message(body: ChannelSendMessageBody):
    """统一发送消息。"""
    import uuid
    from datetime import datetime, timezone

    from app.channels import ChannelRegistry
    from app.channels.base import UnifiedMessage
    from app.services.message_store import save_message

    reg = ChannelRegistry()
    try:
        adapter = reg.get(body.channel_type)
    except KeyError:
        return {"success": False, "error": f"未注册的渠道类型: {body.channel_type}"}
    result = await adapter.send_message(body.contact_id, body.content)
    if not result.get("success", False):
        return {
            "success": False,
            "error": result.get("error") or result.get("message") or "渠道发送失败",
            "data": {"message_id": "", "channel_result": result},
        }

    now = datetime.now(timezone.utc).isoformat()
    msg = UnifiedMessage(
        id=str(uuid.uuid4()),
        customer_id=body.customer_id,
        channel_type=body.channel_type,
        contact_id=body.contact_id,
        contact_name="",
        direction="outbound",
        content=body.content,
        content_type="text",
        metadata=result,
        created_at=now,
    )
    try:
        save_message(msg)
        persisted = True
        persist_error = ""
    except Exception as exc:
        logger.warning("发送成功但消息落库失败: %s", exc)
        persisted = False
        persist_error = str(exc)
    return {
        "success": True,
        "data": {
            "message_id": msg.id if persisted else "",
            "channel_result": result,
            "persisted": persisted,
            "persist_error": persist_error,
        },
    }


@router.get("/messages/unread-count")
def get_unread_summary(
    current_user: CurrentUser,
    customer_id: Optional[int] = None,
):
    """未读消息汇总。

    - 不传 customer_id：返回当前用户团队所有客户的未读汇总
    - 传 customer_id：仅返回该客户的未读数

    返回: { success, data: { total, by_customer: { customer_id: count, ... } } }
    """
    from app.services.message_store import get_unread_count, get_unread_summary as _summary
    from app.services.pipeline import list_pipeline_client_summaries

    if customer_id is not None:
        total = get_unread_count(int(customer_id))
        return {
            "success": True,
            "data": {
                "total": total,
                "by_customer": {str(int(customer_id)): total} if total > 0 else {},
            },
        }

    # 团队隔离：先取团队可见的客户 ID 集合
    team_id = current_user.get("team_id")
    all_clients = list_pipeline_client_summaries()
    visible_ids = {int(c["customer_id"]) for c in all_clients if c.get("customer_id")}

    summary = _summary()
    if visible_ids:
        filtered_by = {
            cid: cnt
            for cid, cnt in summary["by_customer"].items()
            if int(cid) in visible_ids
        }
        filtered_total = sum(filtered_by.values())
    else:
        filtered_by = summary["by_customer"]
        filtered_total = summary["total"]

    return {
        "success": True,
        "data": {
            "total": filtered_total,
            "by_customer": filtered_by,
            "team_id": team_id,
        },
    }


@router.post("/messages/mark-read")
def mark_messages_read(body: MarkReadBody, current_user: CurrentUser):
    """标记消息已读。

    优先级：message_ids > customer_id > all=true
    团队隔离：customer_id 必须是当前用户团队可见的客户。
    """
    from app.services.message_store import mark_all_as_read, mark_as_read
    from app.services.pipeline import list_pipeline_client_summaries

    team_id = current_user.get("team_id")
    visible_ids: set[int] | None = None
    if team_id:
        visible_ids = {int(c["customer_id"]) for c in list_pipeline_client_summaries() if c.get("customer_id")}

    updated = 0
    if body.message_ids:
        # 按 id 标记：限定到可见客户的消息
        # 先取这些 id 对应的 customer_id，过滤后再标记
        from app.services.message_store import _connect
        from app.services.message_store import ensure_messages_schema
        ensure_messages_schema()
        with _connect() as conn:
            placeholders = ",".join("?" for _ in body.message_ids)
            rows = conn.execute(
                f"SELECT id, customer_id FROM kellai_messages WHERE id IN ({placeholders})",
                body.message_ids,
            ).fetchall()
        if visible_ids is not None:
            allowed_ids = [r["id"] for r in rows if int(r["customer_id"]) in visible_ids]
        else:
            allowed_ids = [r["id"] for r in rows]
        if allowed_ids:
            updated += mark_as_read(allowed_ids)
    elif body.customer_id is not None:
        cid = int(body.customer_id)
        if visible_ids is not None and cid not in visible_ids:
            return {"success": False, "error": "该客户不在当前团队中"}
        updated += mark_all_as_read(customer_id=cid)
    elif body.all:
        # 全量模式：只标记可见客户的未读
        if visible_ids is None:
            updated += mark_all_as_read()
        else:
            for cid in visible_ids:
                updated += mark_all_as_read(customer_id=cid)

    return {"success": True, "data": {"updated": updated}}


@router.get("/customers")
def get_customers(
    current_user: CurrentUser,
    stage: str = "",
    channel: str = "",
    q: str = "",
    tag: str = "",
    min_ai_score: float = 0.0,
    limit: int = 500,
):
    """客户列表（复用 pipeline 逻辑，支持搜索与多维筛选）。"""
    from app.services.pipeline import PIPELINE_STAGES, list_pipeline_client_summaries

    clients = list_pipeline_client_summaries()

    # 按阶段筛选
    if stage:
        clients = [c for c in clients if c.get("stage") == stage]

    # 按渠道筛选
    if channel:
        clients = [c for c in clients if channel in (c.get("channel_sources") or [])]

    # 按标签筛选（手动标签或 AI 标签）
    if tag:
        clients = [
            c for c in clients
            if tag in (c.get("tags") or []) or tag in (c.get("ai_tags") or [])
        ]

    # 关键词搜索（姓名/公司/邮箱/电话/登录名）
    if q.strip():
        ql = q.strip().lower()
        search_fields = ("display_name", "name", "company", "email", "phone", "username")
        clients = [
            c for c in clients
            if any(ql in str(c.get(f) or "").lower() for f in search_fields)
        ]

    # 按 AI 评分筛选
    if min_ai_score > 0.0:
        clients = [c for c in clients if float(c.get("ai_score") or 0.0) >= min_ai_score]

    total = len(clients)
    clients = clients[: max(1, int(limit))]

    return {
        "success": True,
        "data": {
            "customers": clients,
            "total": total,
            "stage_definitions": PIPELINE_STAGES,
        },
    }


class CustomerProfileBody(BaseModel):
    """客户资料创建/更新请求体。"""
    name: str = Field(default="", max_length=128)
    company: str = Field(default="", max_length=256)
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=4000)
    owner: str = Field(default="", max_length=128)
    source: str = Field(default="", max_length=64)
    stage: str = Field(default="", max_length=32)
    tags: list[str] = Field(default_factory=list, max_length=50)
    channel_sources: list[str] = Field(default_factory=list, max_length=50)


class CustomerBatchBody(BaseModel):
    """客户批量操作请求体。action: delete | set_stage | add_tag | remove_tag"""
    customer_ids: list[int] = Field(default_factory=list, max_length=1000)
    action: str = Field(..., min_length=1, max_length=32)
    stage: str = Field(default="", max_length=32)
    tag: str = Field(default="", max_length=64)


@router.post("/customers")
def create_customer_endpoint(body: CustomerProfileBody, current_user: CurrentUser):
    """新建客户。"""
    from app.services.pipeline import create_customer

    if not (body.name.strip() or body.company.strip()):
        raise HTTPException(status_code=400, detail={"message": "请至少填写客户姓名或公司名称"})

    operator = str(current_user.get("display_name") or current_user.get("email") or "")
    doc = create_customer(body.model_dump(), username=operator)
    return {"success": True, "data": {"customer_id": doc.get("customer_id"), "pipeline": doc}}


@router.post("/customers/batch")
def batch_customers_endpoint(body: CustomerBatchBody, current_user: CurrentUser):
    """客户批量操作：删除 / 改阶段 / 增删标签。"""
    from app.services.pipeline import (
        add_customer_tag,
        delete_pipeline,
        remove_customer_tag,
        set_pipeline_stage,
    )

    action = body.action.strip()
    valid_actions = {"delete", "set_stage", "add_tag", "remove_tag"}
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail={"message": f"不支持的操作: {action}"})

    affected = 0
    for cid in body.customer_ids:
        try:
            if action == "delete":
                if delete_pipeline(int(cid)):
                    affected += 1
            elif action == "set_stage" and body.stage:
                set_pipeline_stage(int(cid), body.stage, source="manual", note="批量改阶段")
                affected += 1
            elif action == "add_tag" and body.tag:
                add_customer_tag(int(cid), body.tag)
                affected += 1
            elif action == "remove_tag" and body.tag:
                remove_customer_tag(int(cid), body.tag)
                affected += 1
        except Exception:  # pragma: no cover - 单条失败不影响其他
            logger.warning("批量客户操作失败: cid=%s action=%s", cid, action, exc_info=True)

    return {"success": True, "data": {"affected": affected, "action": action}}


@router.put("/customers/{customer_id}")
def update_customer_endpoint(customer_id: int, body: CustomerProfileBody, current_user: CurrentUser):
    """更新客户资料。"""
    from app.services.pipeline import update_customer_profile

    operator = str(current_user.get("display_name") or current_user.get("email") or "")
    doc = update_customer_profile(int(customer_id), body.model_dump(), username=operator)
    return {"success": True, "data": {"customer_id": doc.get("customer_id"), "pipeline": doc}}


@router.delete("/customers/{customer_id}")
def delete_customer_endpoint(customer_id: int, current_user: CurrentUser):
    """删除客户。"""
    from app.services.pipeline import delete_pipeline

    deleted = delete_pipeline(int(customer_id))
    return {"success": bool(deleted), "data": {"customer_id": int(customer_id), "deleted": bool(deleted)}}


@router.get("/status")
def status():
    return {
        "success": True,
        "data": {
            "product": "客来来",
            "version": "0.1.0",
            "independent": True,
        },
    }


@router.get("/tts/status")
def tts_status():
    """查询云端语音能力。"""
    from app.services.tts_runtime import speech_status

    return speech_status()


@router.post("/tts/audio")
def tts_audio(body: TtsSpeakBody):
    """通过 MiMo/Azure 云端 TTS 生成音频，由前端播放。"""
    from urllib.parse import quote

    from app.services.tts_runtime import synthesize_tts_audio

    try:
        result = synthesize_tts_audio(body.text, voice=body.voice, rate=body.rate)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=result.audio,
        media_type="audio/wav",
        headers={
            "X-Kellai-TTS-Provider": result.provider,
            "X-Kellai-TTS-Voice": quote(result.voice, safe=""),
            "X-Kellai-TTS-Model": result.model,
            "X-Kellai-TTS-Cache": "HIT" if result.cached else "MISS",
            "X-Kellai-TTS-Cache-Key": result.cache_key,
        },
    )


@router.post("/tts/speak")
def tts_speak(body: TtsSpeakBody):
    """兼容接口：仅验证云端 TTS 可合成。"""
    from app.services.tts_runtime import speak_text

    result = speak_text(body.text, voice=body.voice, rate=body.rate)
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("message", "云端语音不可用"))
    return result


@router.post("/tts/stop")
def tts_stop():
    """兼容接口：后端不再拥有播放进程。"""
    from app.services.tts_runtime import stop_speech

    return stop_speech()


@router.post("/demo/simulate-customer-behavior")
async def simulate_customer_behavior(body: SimulateCustomerBehaviorBody):
    """生成一批贴近中小商家场景的模拟客户进线，并跑完整闭环。"""
    import time

    from app.services.message_store import push_inbox
    from app.services.growth_loop import customer_message_context
    from app.services.pipeline import _stage_rank, normalize_stage_id

    scenarios = [
        {
            "key": "late_price_inquiry",
            "label": "夜间价格咨询",
            "channel_type": "douyin",
            "contact_name": "抖音-夜间咨询",
            "content": "你们这个多少钱？我晚上刷到的，想看一下套餐和案例。我们有 3 个门店，每天大概 80 条消息。",
            "expected_stage": "intake_done",
        },
        {
            "key": "repeat_customer_discount",
            "label": "老客户复购优惠",
            "channel_type": "wechat",
            "contact_name": "微信-私域复购",
            "content": "之前买过一次，老客户还有优惠吗？合适的话这周再订",
            "expected_stage": "intake",
        },
        {
            "key": "form_submitted",
            "label": "需求表已提交",
            "channel_type": "miniprogram",
            "contact_name": "小程序-留资客户",
            "content": "我已经提交需求表了，麻烦尽快给我一个方案",
            "expected_stage": "intake_done",
        },
        {
            "key": "price_sensitive_compare",
            "label": "比价异议",
            "channel_type": "pdd",
            "contact_name": "拼多多-售前比价",
            "content": "别家便宜一点，你们能不能优惠？有现货吗",
            "expected_stage": "intake",
        },
        {
            "key": "contract_urgent",
            "label": "签约交付追问",
            "channel_type": "wework",
            "contact_name": "企微-签约推进",
            "content": "合同怎么签？如果今天付款多久能开始交付",
            "expected_stage": "contract_pending",
        },
        {
            "key": "social_link_request",
            "label": "社媒求链接",
            "channel_type": "xiaohongshu",
            "contact_name": "小红书-求链接",
            "content": "怎么买呀？求链接，可以加微信详细说吗",
            "expected_stage": "intake",
        },
        {
            "key": "paid_delivery",
            "label": "付款后交付",
            "channel_type": "wework",
            "contact_name": "企微-付款客户",
            "content": "合同确认了，已经付款了，发我交付清单吧",
            "expected_stage": "signed",
        },
        {
            "key": "low_intent_noise",
            "label": "低意向闲聊",
            "channel_type": "douyin",
            "contact_name": "抖音-围观用户",
            "content": "先收藏了，回头看看，你们页面做得还不错",
            "expected_stage": "connected",
        },
    ]

    selected = scenarios[: body.count]
    created_ids: list[str] = []
    scenario_refs: list[dict[str, Any]] = []
    now_ms = int(time.time() * 1000)
    for idx, scenario in enumerate(selected):
        channel_type = scenario["channel_type"]
        # 当前注册表没有 xiaohongshu 独立渠道，先按 douyin 类新媒体私信统一进入。
        stored_channel = "douyin" if channel_type == "xiaohongshu" else channel_type
        contact_id = f"sim_{channel_type}_{now_ms}_{idx}"
        mid = push_inbox(
            stored_channel,
            contact_id=contact_id,
            contact_name=scenario["contact_name"],
            direction="inbound",
            content=scenario["content"],
            metadata={
                "scenario": channel_type,
                "scenario_key": scenario["key"],
                "expected_stage": scenario["expected_stage"],
                "simulated": True,
            },
        )
        created_ids.append(mid)
        scenario_refs.append({**scenario, "stored_channel": stored_channel, "contact_id": contact_id, "message_id": mid})

    synced = await sync_channel_inbox(ChannelSyncInboxBody(limit=max(body.count, 20)))
    saved_messages = synced.get("data", {}).get("messages", []) if isinstance(synced.get("data"), dict) else []
    by_scenario: dict[str, dict[str, Any]] = {}
    for msg in saved_messages:
        meta = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        key = str(meta.get("scenario_key") or "")
        if key:
            by_scenario[key] = msg

    results: list[dict[str, Any]] = []
    for scenario in scenario_refs:
        expected_stage = normalize_stage_id(str(scenario.get("expected_stage") or "connected"))
        msg = by_scenario.get(str(scenario["key"])) or {}
        customer_id = int(msg.get("customer_id") or 0)
        ctx = customer_message_context(customer_id) if customer_id > 0 else {}
        final_stage = normalize_stage_id(str(ctx.get("stage") or "idle"))
        passed = (
            customer_id > 0
            and _stage_rank(final_stage) >= _stage_rank(expected_stage)
            and float(ctx.get("ai_score") or 0.0) > 0
            and bool(str(ctx.get("next_action") or "").strip())
        )
        results.append(
            {
                "key": scenario["key"],
                "label": scenario["label"],
                "channel_type": scenario["channel_type"],
                "stored_channel": scenario["stored_channel"],
                "contact_id": scenario["contact_id"],
                "customer_id": customer_id,
                "expected_stage": expected_stage,
                "final_stage": final_stage,
                "stage_label": ctx.get("stage_label") or "",
                "ai_score": ctx.get("ai_score") or 0.0,
                "next_action": ctx.get("next_action") or "",
                "passed": passed,
            }
        )

    passed_count = sum(1 for item in results if item["passed"])
    return {
        "success": True,
        "data": {
            "created": len(created_ids),
            "scenario_set": body.scenario_set,
            "inbox_message_ids": created_ids,
            "sync": synced.get("data", {}),
            "summary": {
                "total": len(results),
                "passed": passed_count,
                "failed": len(results) - passed_count,
                "synced": synced.get("data", {}).get("synced", 0) if isinstance(synced.get("data"), dict) else 0,
            },
            "scenario_results": results,
            "passed": bool(results) and passed_count == len(results),
        },
    }


@router.post("/demo/llm-full-flow-test")
async def llm_full_flow_test(body: LLMFullFlowTestBody):
    """用 LLM 扮演客户，跑多轮消息、销售回复、漏斗推进与断言报告。"""
    from app.services.llm_customer_simulator import run_llm_full_flow_simulation

    result = await run_llm_full_flow_simulation(
        turns=body.turns,
        target_stage=body.target_stage,
        channel_type=body.channel_type,
        scenario=body.scenario,
        use_llm=body.use_llm,
        auto_reply=body.auto_reply,
        require_llm=body.require_llm,
    )
    return {"success": True, "data": result}


@router.post("/demo/closed-loop-audit")
async def closed_loop_audit(body: ClosedLoopAuditBody):
    """跑产品级闭环验收报告：客户、消息、AI、漏斗、LLM 成交链路。"""
    from app.services.closed_loop_audit import run_closed_loop_audit

    result = await run_closed_loop_audit(
        require_llm=body.require_llm,
        target_stage=body.target_stage,
    )
    return {"success": True, "data": result}


@router.get("/demo/closed-loop-audit/latest")
async def latest_closed_loop_audit():
    """读取最近一次产品级闭环验收报告，用于交付复核和页面刷新后回看。"""
    from app.services.closed_loop_audit import latest_closed_loop_audit_report

    return {"success": True, "data": latest_closed_loop_audit_report()}


@router.get("/clients")
def list_clients():
    from app.services.pipeline import list_pipeline_client_summaries

    return {"success": True, "data": {"clients": list_pipeline_client_summaries()}}


@router.get("/pipeline/funnel")
def pipeline_funnel(max_clients_per_stage: int = 8):
    from app.services.pipeline import PIPELINE_STAGES, build_pipeline_funnel_summary

    data = build_pipeline_funnel_summary(max_clients_per_stage=max_clients_per_stage)
    return {"success": True, "data": {**data, "stage_definitions": PIPELINE_STAGES}}


@router.get("/pipeline")
def get_pipeline(
    customer_id: int | None = None,
    market_user_id: int | None = None,
    username: str = "",
    auto_advance: bool = False,
    channel: str = "",
    min_ai_score: float = 0.0,
):
    from app.services.crm_store import get_crm_bundle_for_customer
    from app.services.pipeline import PIPELINE_STAGES, auto_advance_pipeline_if_ready, load_pipeline

    uid = int(customer_id or market_user_id or 0)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    advanced = False
    if auto_advance:
        doc, advanced = auto_advance_pipeline_if_ready(uid, username=username)
    else:
        doc = load_pipeline(uid, username=username)
    # 按渠道和 AI 评分过滤（仅当指定了筛选参数时生效）
    if channel.strip():
        sources = list(doc.get("channel_sources") or [])
        if channel.strip() not in sources:
            return {"success": False, "error": f"客户未触达渠道: {channel.strip()}"}
    if min_ai_score > 0.0:
        score = float(doc.get("ai_score") or 0.0)
        if score < min_ai_score:
            return {"success": False, "error": f"AI 评分 {score} 低于阈值 {min_ai_score}"}
    return {
        "success": True,
        "data": {
            "pipeline": doc,
            "stages": PIPELINE_STAGES,
            "advanced": advanced,
            "crm": get_crm_bundle_for_customer(uid),
        },
    }


@router.get("/pipeline/query")
def query_pipelines(
    stage: str = "",
    channel: str = "",
    min_ai_score: float = 0.0,
    limit: int = 100,
):
    """高级查询 pipeline（从 SQLite 查询，支持按阶段、渠道、AI 评分筛选）。"""
    from app.services.crm_store import query_pipelines_from_sqlite

    rows = query_pipelines_from_sqlite(
        stage=stage,
        channel=channel,
        min_ai_score=min_ai_score,
        limit=limit,
    )
    return {"success": True, "data": {"pipelines": rows, "total": len(rows)}}


def _apply_pipeline(body: PipelineBody) -> dict[str, Any]:
    from app.services.pipeline import load_pipeline, save_pipeline, set_pipeline_stage

    uid = _cid(body)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    doc = load_pipeline(uid, username=body.username)
    if body.stage:
        try:
            doc = set_pipeline_stage(
                uid,
                body.stage,
                username=body.username,
                source="manual" if body.manual else "api",
                note=body.note,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
    if body.intake_sent:
        doc["intake_sent"] = True
        doc = save_pipeline(doc)
    return {"success": True, "data": {"pipeline": doc}}


@router.put("/pipeline")
@router.post("/pipeline/stage")
def post_pipeline_stage(body: PipelineBody):
    return _apply_pipeline(body)


@router.post("/pipeline/auto-advance")
async def auto_advance(body: PipelineBody):
    from app.services.pipeline import auto_advance_pipeline_if_ready

    uid = _cid(body)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    doc, advanced = auto_advance_pipeline_if_ready(uid, username=body.username)
    return {"success": True, "data": {"pipeline": doc, "advanced": advanced}}


@router.post("/analyze")
async def analyze(body: AnalyzeBody):
    from app.services.pipeline import PIPELINE_STAGES, analyze_customer_pipeline, save_pipeline
    from app.services.wechat_bridge import build_starred_group_feed, get_bindings_for_user

    uid = _cid(body)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    has_binding = body.has_binding or bool(get_bindings_for_user(uid))
    feed = build_starred_group_feed(limit=20, customer_id=uid)
    texts = [str(x.get("content") or x.get("message") or "") for x in feed if x.get("content") or x.get("message")]
    doc = analyze_customer_pipeline(
        uid,
        username=body.username,
        message_texts=texts,
        has_binding=has_binding,
        intake_sent=body.intake_sent,
    )
    if texts:
        doc["last_message_preview"] = texts[0][:500]
        doc = save_pipeline(doc)
    connected_welcome = None
    if str(doc.get("stage")) == "connected" and has_binding:
        from app.services.intake_notice import maybe_send_connected_welcome

        connected_welcome = maybe_send_connected_welcome(uid, username=body.username)
    return {
        "success": True,
        "data": {
            "pipeline": doc,
            "stages": PIPELINE_STAGES,
            "message_count": len(texts),
            "connected_welcome": connected_welcome,
        },
    }


@router.post("/landing/sync")
async def landing_sync(body: LandingSyncBody, request: Request):
    from app.services.demand_form import verify_webhook_secret
    from app.services.landing_crm import apply_landing_submission_to_funnel

    if not verify_webhook_secret(request.headers.get("x-kellai-webhook-secret")):
        return {"success": False, "error": "unauthorized"}
    doc = apply_landing_submission_to_funnel(body.model_dump(), notify_wechat=False)
    return {"success": True, "data": {"pipeline": doc}}


@router.get("/demand-form/link")
def demand_form_link(customer_id: int, client_name: str = "", brief: str = ""):
    from app.services.demand_form import build_intake_form_url

    url = build_intake_form_url(int(customer_id), brief=brief, client_name=client_name)
    return {"success": True, "data": {"form_url": url}}


@router.post("/demand-form/finalize")
async def demand_form_finalize(body: PipelineBody):
    from app.services.intake_finalize import finalize_intake_submission
    from app.services.pipeline import load_pipeline

    uid = _cid(body)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    doc = load_pipeline(uid, username=body.username)
    if not doc.get("intake_submitted_at"):
        return {"success": False, "error": "尚未同步到需求提交记录"}
    doc, meta = finalize_intake_submission(uid, doc, username=body.username, notify_wechat=True)
    return {"success": True, "data": {"pipeline": doc, "finalize": meta}}


@router.get("/crm")
def crm_bundle(customer_id: int):
    from app.services.crm_store import get_crm_bundle_for_customer

    return {"success": True, "data": get_crm_bundle_for_customer(int(customer_id))}


@router.post("/crm/sync")
async def crm_sync(body: PipelineBody):
    from app.services.crm_store import get_crm_bundle_for_customer, sync_crm_from_pipeline_doc
    from app.services.pipeline import load_pipeline, save_pipeline

    uid = _cid(body)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    doc = load_pipeline(uid, username=body.username)
    doc = sync_crm_from_pipeline_doc(doc)
    doc = save_pipeline(doc)
    return {"success": True, "data": {"pipeline": doc, "crm": get_crm_bundle_for_customer(uid)}}


@router.get("/wechat/groups")
def wechat_groups(keyword: str = "", limit: int = 80):
    from app.services.wechat_bridge import list_group_contacts

    rows = list_group_contacts(keyword=keyword or None, limit=limit)
    return {"success": True, "data": rows, "total": len(rows)}


@router.get("/wechat/bindings/{customer_id}")
def wechat_bindings_get(customer_id: int):
    from app.services.wechat_bridge import get_bindings_for_user

    return {"success": True, "data": get_bindings_for_user(int(customer_id))}


@router.put("/wechat/bindings/{customer_id}")
def wechat_bindings_put(customer_id: int, body: BindingsBody):
    from app.services.wechat_bridge import save_bindings_for_user

    return save_bindings_for_user(int(customer_id), body.contact_ids)


@router.post("/wechat/send")
async def wechat_send(body: WechatSendBody):
    from app.desktop_automation.service import get_desktop_automation_service
    from app.services.pipeline import load_pipeline, save_pipeline
    from app.services.wechat_bridge import get_bindings_for_user

    uid = _cid(body)
    contact = body.contact_name.strip()
    bindings = get_bindings_for_user(uid) if uid > 0 else []
    if not contact and bindings:
        first = bindings[0]
        contact = str(first.get("contact_name") or first.get("name") or "").strip()
    if not contact:
        return {"success": False, "error": "请先保存群聊绑定，或确认群名称"}
    result = get_desktop_automation_service().send_wechat_message(contact, body.message.strip())
    sent = bool(result.get("success")) and bool(result.get("message_sent", result.get("success")))
    if sent and uid > 0:
        doc = load_pipeline(uid, username=body.username)
        if doc.get("stage") in ("idle", "connected"):
            doc["stage"] = "connected"
            save_pipeline(doc)
    return {"success": sent, "data": result}


@router.post("/wechat/send-connected-welcome")
async def send_connected_welcome(body: WelcomeBody):
    from app.services.intake_notice import maybe_send_connected_welcome
    from app.services.pipeline import load_pipeline, save_pipeline

    uid = _cid(body)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    doc = load_pipeline(uid, username=body.username)
    if str(doc.get("stage") or "idle") == "idle":
        doc["stage"] = "connected"
        save_pipeline(doc)
    out = maybe_send_connected_welcome(
        uid,
        username=body.username,
        contact_name=body.contact_name.strip(),
        force=body.force,
    )
    return {"success": bool(out.get("sent")), "data": out}


@router.post("/wechat/send-intake-notice")
async def send_intake_notice(body: IntakeNoticeBody):
    from app.services.intake_notice import maybe_send_intake_form_notice
    from app.services.pipeline import load_pipeline, save_pipeline

    uid = _cid(body)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    doc = load_pipeline(uid, username=body.username)
    stage = str(doc.get("stage") or "idle")
    if stage in ("idle", "connected"):
        doc["stage"] = "intake"
        save_pipeline(doc)
    out = maybe_send_intake_form_notice(
        uid,
        username=body.username,
        contact_name=body.contact_name.strip(),
        brief=body.brief.strip(),
        force=body.force,
    )
    return {"success": bool(out.get("sent")), "data": out}


@router.get("/wechat/llm-status")
def wechat_llm_status():
    from app.services.passive_monitor import probe_passive_llm_ready

    return {"success": True, "data": probe_passive_llm_ready()}


@router.get("/ai/llm-status")
def ai_llm_status():
    """AI 助手配置页用的 LLM 状态探测（与 wechat/llm-status 等价，但不再依赖微信渠道）。"""
    from app.services.passive_monitor import probe_passive_llm_ready

    return {"success": True, "data": probe_passive_llm_ready()}


@router.put("/ai/llm-config")
def ai_save_llm_config(body: LLMConfigBody):
    """保存真实 LLM 配置，并立即做一次真实连通探测。"""
    from app.services.llm_config import probe_llm_connection, public_config, save_config

    save_config(body.model_dump())
    probe_llm_connection(update_disk=True)
    data = public_config()
    return {"success": True, "data": data}


@router.post("/ai/llm-probe")
def ai_probe_llm_connection():
    """手动触发真实 LLM 连通测试，返回脱敏结果。"""
    from app.services.llm_config import probe_llm_connection, public_config

    probe = probe_llm_connection(update_disk=True)
    data = public_config()
    data["probe"] = probe
    return {"success": bool(probe.get("success")), "data": data}


@router.get("/ai/llm-diagnostics")
def ai_llm_diagnostics():
    """返回脱敏 LLM 配置诊断，帮助确认 Key 是否被当前后端读取。"""
    from app.services.llm_config import diagnostics

    return {"success": True, "data": diagnostics()}


@router.post("/wechat/passive-poll")
async def passive_poll(body: PassivePollBody):
    from app.services.passive_monitor import passive_poll_once

    uid = _cid(body)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    out = passive_poll_once(
        customer_id=uid,
        username=body.username,
        dry_run=body.dry_run,
        auto_reply=body.auto_reply,
        max_replies=body.max_replies,
        use_llm=body.use_llm,
        skip_sync=body.skip_sync,
    )
    return {"success": bool(out.get("success")), "data": out}


@router.get("/wechat/passive-loop")
def passive_loop_get(customer_id: int, username: str = ""):
    from app.services.passive_monitor import get_passive_poll_config

    return {"success": True, "data": get_passive_poll_config(customer_id, username=username)}


@router.post("/wechat/passive-loop")
@router.put("/wechat/passive-loop")
def passive_loop_save(body: PassiveLoopBody):
    from app.services.passive_monitor import save_passive_poll_config

    uid = _cid(body)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    data = save_passive_poll_config(
        uid,
        username=body.username,
        poll_enabled=body.poll_enabled,
        poll_interval_sec=body.poll_interval_sec,
    )
    return {"success": True, "data": data}


@router.post("/wechat/passive-reset-watch")
def passive_reset_watch(body: PassiveLoopBody):
    from app.services.passive_monitor import reset_passive_watch

    uid = _cid(body)
    if uid <= 0:
        return {"success": False, "error": "customer_id required"}
    state = reset_passive_watch(uid, username=body.username)
    return {"success": True, "data": state}


# ---------------------------------------------------------------------------
# AI 跟单助手 API
# ---------------------------------------------------------------------------


@router.post("/ai/intent")
async def ai_analyze_intent(body: IntentBody, request: Request, _rl: None = Depends(enforce_llm_rate_limit)):
    """分析消息意图"""
    from app.services.ai_copilot import analyze_intent

    result = analyze_intent(body.message, context=body.context)
    return {"success": True, "data": result}


@router.post("/ai/suggest-reply")
async def ai_suggest_reply(
    body: SuggestReplyBody,
    request: Request,
    _rl: None = Depends(enforce_llm_rate_limit),
):
    """推荐回复话术"""
    from app.services.ai_copilot import suggest_reply
    from app.services.pipeline import load_pipeline

    uid = int(body.customer_id or body.market_user_id or 0)
    stage = body.stage
    history: list[str] = []
    if uid > 0:
        doc = load_pipeline(uid)
        if not stage:
            stage = str(doc.get("stage") or "idle")
        # 获取最近消息作为 history
        from app.services.message_store import get_messages

        msgs = get_messages(uid, limit=5)
        history = [m.content for m in msgs]
    suggestions = suggest_reply(
        uid,
        message=body.message,
        intent=body.intent,
        stage=stage,
        history=history,
    )
    return {"success": True, "data": {"suggestions": suggestions}}


@router.post("/ai/auto-reply")
async def ai_auto_reply(
    body: AutoReplyBody,
    request: Request,
    _rl: None = Depends(enforce_llm_rate_limit),
):
    """生成自动回复草稿"""
    from app.services.ai_copilot import generate_auto_reply
    from app.services.pipeline import load_pipeline

    uid = int(body.customer_id or body.market_user_id or 0)
    stage = body.stage
    history: list[str] = []
    if uid > 0:
        doc = load_pipeline(uid)
        if not stage:
            stage = str(doc.get("stage") or "idle")
        from app.services.message_store import get_messages

        msgs = get_messages(uid, limit=5)
        history = [m.content for m in msgs]
    result = generate_auto_reply(
        uid,
        message=body.message,
        intent=body.intent,
        stage=stage,
        history=history,
    )
    return {"success": True, "data": result}


@router.get("/ai/profile/{customer_id}")
async def ai_customer_profile(
    customer_id: int,
    request: Request,
    _rl: None = Depends(enforce_llm_rate_limit),
):
    """获取客户 AI 画像"""
    from app.services.ai_copilot import generate_customer_profile
    from app.services.message_store import get_messages

    msgs = get_messages(int(customer_id), limit=30)
    msg_dicts = [
        {"content": m.content, "direction": m.direction, "channel_type": m.channel_type}
        for m in msgs
    ]
    profile = generate_customer_profile(int(customer_id), messages=msg_dicts if msg_dicts else None)
    return {"success": True, "data": profile}


@router.get("/ai/operating-insight/{customer_id}")
async def ai_customer_operating_insight(
    customer_id: int,
):
    """获取客户跨渠道记忆、风险、主动任务和管理洞察。"""
    from app.services.growth_loop import customer_agent_operating_insight

    insight = customer_agent_operating_insight(int(customer_id))
    return {"success": True, "data": insight}


@router.get("/ai/quality-inspection/{customer_id}")
async def ai_customer_quality_inspection(
    customer_id: int,
):
    """获取客户客服质检、合规风险和主管复盘建议。"""
    from app.services.quality_inspection import inspect_customer_conversation

    report = inspect_customer_conversation(int(customer_id))
    return {"success": True, "data": report}


@router.get("/ai/service-tickets/{customer_id}")
async def ai_customer_service_tickets(
    customer_id: int,
):
    """获取客户转人工/主管工单汇总。"""
    from app.services.service_tickets import service_ticket_summary

    return {"success": True, "data": service_ticket_summary(int(customer_id))}


@router.post("/ai/service-tickets")
async def ai_create_service_ticket(
    body: ServiceTicketCreateBody,
):
    """创建转人工/主管工单，可从质检报告自动生成。"""
    from app.services.service_tickets import create_service_ticket, create_ticket_from_quality

    if body.from_quality:
        ticket = create_ticket_from_quality(
            int(body.customer_id),
            assignee=body.assignee,
            sla_minutes=body.sla_minutes,
        )
    else:
        ticket = create_service_ticket(body.model_dump())
    return {"success": True, "data": ticket}


@router.post("/ai/service-tickets/{ticket_id}/assign")
async def ai_assign_service_ticket(
    ticket_id: str,
    body: ServiceTicketAssignBody,
):
    """指派工单给主管/人工客服。"""
    from app.services.service_tickets import assign_service_ticket

    return {"success": True, "data": assign_service_ticket(ticket_id, body.assignee, actor=body.actor)}


@router.post("/ai/service-tickets/{ticket_id}/resolve")
async def ai_resolve_service_ticket(
    ticket_id: str,
    body: ServiceTicketResolveBody,
):
    """解决工单，并可将会话回托给 AI 继续跟进。"""
    from app.services.service_tickets import resolve_service_ticket

    return {
        "success": True,
        "data": resolve_service_ticket(
            ticket_id,
            body.resolution,
            actor=body.actor,
            rehost_to_ai=body.rehost_to_ai,
        ),
    }


@router.get("/ai/service-learning/{customer_id}")
async def ai_customer_service_learning(
    customer_id: int,
):
    """读取客户服务自学习指标与已沉淀知识，不产生写入。"""
    from app.services.service_learning import run_service_learning

    return {"success": True, "data": run_service_learning(int(customer_id), persist=False)}


@router.post("/ai/service-learning/{customer_id}")
async def ai_run_customer_service_learning(
    customer_id: int,
    body: ServiceLearningBody | None = None,
):
    """将质检/工单处理结果沉淀为可检索知识和服务优化指标。"""
    from app.services.service_learning import run_service_learning

    persist = True if body is None else body.persist
    return {"success": True, "data": run_service_learning(int(customer_id), persist=persist)}


@router.get("/ai/outbound-calls/{customer_id}")
async def ai_customer_outbound_calls(
    customer_id: int,
):
    """读取客户 AI 外呼任务、通话纪要与电话消息数量。"""
    from app.services.outbound_call import outbound_call_summary

    return {"success": True, "data": outbound_call_summary(int(customer_id))}


@router.post("/ai/outbound-calls")
async def ai_plan_outbound_call(
    body: OutboundCallPlanBody,
):
    """生成 AI 外呼任务和电话话术。"""
    from app.services.outbound_call import plan_outbound_call

    return {
        "success": True,
        "data": plan_outbound_call(
            int(body.customer_id),
            purpose=body.purpose,
            assignee=body.assignee,
            actor="desktop",
        ),
    }


@router.post("/ai/outbound-calls/{call_id}/execute")
async def ai_execute_outbound_call(
    call_id: str,
    body: OutboundCallExecuteBody,
):
    """执行本地模拟 AI 外呼，写入电话消息并推进客户漏斗。"""
    from app.services.outbound_call import execute_outbound_call

    return {
        "success": True,
        "data": execute_outbound_call(
            call_id,
            outcome=body.outcome,
            note=body.note,
            actor=body.actor,
        ),
    }


@router.get("/ai/self-service/{customer_id}")
async def ai_customer_self_service(
    customer_id: int,
):
    """读取客户 AI 自助解决记录与转人工指标。"""
    from app.services.self_service_resolution import self_service_summary

    return {"success": True, "data": self_service_summary(int(customer_id))}


@router.post("/ai/self-service/{customer_id}")
async def ai_run_customer_self_service(
    customer_id: int,
    body: SelfServiceResolutionBody | None = None,
):
    """执行 AI 自助解决：知识库命中则自动回复，未命中则转人工工单。"""
    from app.services.self_service_resolution import run_self_service_resolution

    payload = body or SelfServiceResolutionBody()
    return {
        "success": True,
        "data": run_self_service_resolution(
            int(customer_id),
            query=payload.query,
            channel_type=payload.channel_type,
            fallback_to_ticket=payload.fallback_to_ticket,
            actor="desktop",
            persist=True,
        ),
    }


@router.get("/ai/agent-assist/{customer_id}")
async def ai_customer_agent_assist(customer_id: int):
    """读取坐席助手建议：自动填单草稿、知识推荐和风险提醒。"""
    from app.services.agent_assist import agent_assist_summary

    return {"success": True, "data": agent_assist_summary(int(customer_id))}


@router.post("/ai/agent-assist/{customer_id}")
async def ai_run_customer_agent_assist(
    customer_id: int,
    body: AgentAssistBody | None = None,
):
    """执行坐席助手闭环：生成并可应用自动填单结果。"""
    from app.services.agent_assist import build_agent_assist

    payload = body or AgentAssistBody()
    return {
        "success": True,
        "data": build_agent_assist(
            int(customer_id),
            persist=payload.persist,
            actor=payload.actor,
        ),
    }


@router.get("/ai/knowledge-base")
async def ai_knowledge_base_list():
    """获取客服知识库文章列表。"""
    from app.services.knowledge_base import list_articles

    return {"success": True, "data": {"articles": list_articles()}}


@router.post("/ai/knowledge-base")
async def ai_knowledge_base_upsert(
    body: KnowledgeArticleBody,
):
    """新增或更新客服知识库文章。"""
    from app.services.knowledge_base import upsert_article

    article = upsert_article(body.model_dump())
    return {"success": True, "data": article}


@router.delete("/ai/knowledge-base/{article_id}")
async def ai_knowledge_base_delete(
    article_id: str,
):
    """删除客服知识库文章。"""
    from app.services.knowledge_base import delete_article

    return {"success": True, "data": {"deleted": delete_article(article_id)}}


@router.post("/ai/knowledge-base/search")
async def ai_knowledge_base_search(
    body: KnowledgeQueryBody,
):
    """检索客服知识库。"""
    from app.services.knowledge_base import search_articles

    return {"success": True, "data": {"items": search_articles(body.query, limit=body.limit)}}


@router.post("/ai/knowledge-base/suggest")
async def ai_knowledge_base_suggest(
    body: KnowledgeQueryBody,
):
    """基于知识库生成可追溯客服回复建议。"""
    from app.services.growth_loop import customer_message_context
    from app.services.knowledge_base import suggest_answer

    context = customer_message_context(int(body.customer_id)) if body.customer_id else {}
    return {"success": True, "data": suggest_answer(body.query, customer_context=context, limit=body.limit)}


@router.get("/ai/reminders")
async def ai_reminders(
    hours: int = 48,
    limit: int = 20,
):
    """获取跟进提醒列表"""
    from app.services.ai_copilot import get_follow_up_reminders

    reminders = get_follow_up_reminders(hours_threshold=hours)
    return {"success": True, "data": {"reminders": reminders[:limit]}}


@router.post("/ai/score/{customer_id}")
async def ai_update_score(
    customer_id: int,
):
    """更新客户 AI 评分"""
    from app.services.ai_copilot import calculate_ai_score
    from app.services.pipeline import load_pipeline, save_pipeline
    from app.services.message_store import get_messages

    uid = int(customer_id)
    msgs = get_messages(uid, limit=30)
    msg_dicts = [{"content": m.content, "direction": m.direction} for m in msgs]
    score = calculate_ai_score(uid, messages=msg_dicts if msg_dicts else None)
    doc = load_pipeline(uid)
    doc["ai_score"] = score
    save_pipeline(doc)
    return {"success": True, "data": {"customer_id": uid, "ai_score": score}}


# ---------------------------------------------------------------------------
# 认证与团队 API
# ---------------------------------------------------------------------------


@router.post("/auth/register")
def auth_register(body: RegisterBody, request: Request):
    """用户注册"""
    from app.services.auth import register_user
    from app.services.rate_limiter import check_register_rate_limit
    from app.main import _get_client_ip

    # 注册限流：防垃圾注册 / DB 膨胀
    ip_key = f"ip:{_get_client_ip(request)}"
    allowed, retry_after = check_register_rate_limit(ip_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"message": "注册请求过于频繁，请稍后再试", "retry_after": round(retry_after, 1)},
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    result = register_user(
        email=body.email,
        phone=body.phone,
        password=body.password,
        display_name=body.display_name or body.name,
    )
    return result


@router.post("/auth/login")
def auth_login(body: LoginBody, request: Request):
    """邮箱/手机号登录

    返回 {"success", "user", "access_token", "refresh_token", "access_expires_at", "refresh_expires_at"}
    """
    from app.services.auth import login_by_email, login_by_phone
    from app.services.rate_limiter import check_login_rate_limit
    from app.main import _get_client_ip

    # 登录限流：按真实 IP（支持 X-Forwarded-For）
    ip_key = f"ip:{_get_client_ip(request)}"
    allowed, retry_after = check_login_rate_limit(ip_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"message": "请求过于频繁，请稍后再试", "retry_after": round(retry_after, 1)},
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    if body.email and body.password:
        return login_by_email(body.email, body.password)
    if body.phone and body.code:
        return login_by_phone(body.phone, body.code)
    return {"success": False, "error": "请提供邮箱+密码或手机号+验证码"}


@router.post("/auth/refresh")
def auth_refresh(body: RefreshBody):
    """用 refresh_token 换发新的 access_token（同时轮换 refresh_token）"""
    from app.services.auth import refresh_access_token

    return refresh_access_token(body.refresh_token)


@router.post("/auth/logout")
def auth_logout(current_user: CurrentUser, request: Request):
    """登出：吊销当前 refresh_token（需客户端在请求头带上 refresh_token）。

    注意：access_token 仍可使用到自然过期，但 server 侧已拒绝该 session。
    """
    from app.services.auth import revoke_session_by_refresh

    refresh_token = request.headers.get("X-Refresh-Token", "").strip()
    if not refresh_token:
        return {"success": False, "error": "缺少 X-Refresh-Token 头"}
    ok = revoke_session_by_refresh(refresh_token)
    return {"success": ok, "message": "已登出" if ok else "未找到会话或已吊销"}


@router.post("/auth/sms/send")
def auth_send_sms(body: LoginBody, request: Request):
    """发送短信验证码（开发模式：验证码打印到日志）"""
    from app.services.auth import generate_sms_code
    from app.services.rate_limiter import check_login_rate_limit
    from app.main import _get_client_ip

    if not body.phone:
        return {"success": False, "error": "手机号不能为空"}
    # 限流检查
    ip_key = f"ip:{_get_client_ip(request)}"
    allowed, retry_after = check_login_rate_limit(ip_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"message": "请求过于频繁，请稍后再试", "retry_after": round(retry_after, 1)},
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    code = generate_sms_code(body.phone)
    if not code:
        return {"success": False, "error": "验证码发送失败，请检查手机号"}
    return {"success": True, "message": "验证码已发送（开发模式：请查看服务器日志）", "code": code}


@router.post("/auth/forgot-password")
def auth_reset_password(body: ResetPasswordBody, request: Request):
    """通过手机验证码重置密码。

    前置：客户端需先调用 /auth/sms/send 获取验证码。
    """
    from app.services.auth import reset_password_by_phone
    from app.services.rate_limiter import check_login_rate_limit
    from app.main import _get_client_ip

    ip_key = f"ip:{_get_client_ip(request)}"
    allowed, retry_after = check_login_rate_limit(ip_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"message": "请求过于频繁，请稍后再试", "retry_after": round(retry_after, 1)},
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    result = reset_password_by_phone(body.phone, body.code, body.new_password)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail={"message": result.get("error", "重置失败")})
    return result


@router.get("/auth/me")
def auth_me(current_user: CurrentUser):
    """获取当前用户信息"""
    return {"success": True, "data": current_user}


@router.put("/auth/me")
def auth_update_me(body: UpdateUserBody, current_user: CurrentUser):
    """更新当前用户信息"""
    from app.services.auth import update_user

    kwargs = {}
    if body.display_name:
        kwargs["display_name"] = body.display_name
    if body.avatar_url:
        kwargs["avatar_url"] = body.avatar_url
    return update_user(current_user["id"], **kwargs)


@router.get("/team")
def get_my_team(current_user: CurrentUser):
    """获取我的团队"""
    from app.services.auth import get_team

    team_id = current_user.get("team_id")
    if not team_id:
        return {"success": False, "error": "您还未加入任何团队"}
    team = get_team(team_id)
    if not team:
        return {"success": False, "error": "团队不存在"}
    return {"success": True, "data": team}


@router.post("/team/invite")
def invite_member(body: InviteBody, current_user: CurrentUser):
    """邀请成员"""
    from app.services.auth import invite_team_member

    team_id = current_user.get("team_id")
    if not team_id:
        return {"success": False, "error": "您还未加入任何团队"}
    return invite_team_member(
        team_id,
        actor_id=int(current_user["id"]),
        email=body.email,
        phone=body.phone,
        role=body.role,
    )


@router.get("/team/members")
def list_members(current_user: CurrentUser):
    """列出团队成员"""
    from app.services.auth import list_team_members

    team_id = current_user.get("team_id")
    if not team_id:
        return {"success": False, "error": "您还未加入任何团队"}
    members = list_team_members(team_id)
    return {"success": True, "data": {"members": members, "total": len(members)}}


@router.put("/team/members/{user_id}/role")
def update_role(user_id: int, body: RoleBody, current_user: CurrentUser):
    """更新成员角色"""
    from app.services.auth import update_member_role

    team_id = current_user.get("team_id")
    if not team_id:
        return {"success": False, "error": "您还未加入任何团队"}
    return update_member_role(
        team_id,
        int(user_id),
        body.role,
        actor_id=int(current_user["id"]),
    )


@router.post("/team/join")
def join_team(body: JoinBody, current_user: CurrentUser):
    """加入团队"""
    from app.services.auth import join_team_by_invite_code

    return join_team_by_invite_code(body.invite_code, current_user["id"])


# ---------------------------------------------------------------------------
# 企微 Webhook 回调
# ---------------------------------------------------------------------------


@router.get("/webhook/wework")
async def wecom_webhook_verify(
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
):
    """企微回调 URL 验证（GET）。

    企微后台配置回调 URL 时，会发 GET 请求验证。
    简化版：直接返回 echostr（生产环境应做签名校验）。
    """
    if echostr:
        return int(echostr)
    return {"success": True, "message": "wework webhook endpoint active"}


@router.post("/webhook/wework")
async def wecom_webhook_receive(request: Request):
    """企微回调消息接收（POST）。

    接收企微推送的消息/事件，写入 inbox。
    企微消息体格式（XML，加密或明文）：
    - 明文模式：直接解析 XML
    - 加密模式：需用 EncodingAESKey 解密（本版本暂只支持明文/兼容模式）

    企微回调数据格式（JSON）：
    {
      "ToUserName": "CorpID",
      "FromUserName": "UserID",
      "Content": "消息内容",
      "MsgType": "text",
      "CreateTime": 1234567890,
      "MsgId": 1234567890123456,
      "AgentID": 1
    }
    """
    import uuid
    from datetime import datetime, timezone

    from app.services.message_store import push_inbox

    content_type = request.headers.get("content-type", "")

    try:
        if "json" in content_type:
            body = await request.json()
        elif "xml" in content_type or "text" in content_type:
            raw = await request.body()
            raw_text = raw.decode("utf-8", errors="replace")
            # 简易 XML 解析
            body = _parse_wecom_xml(raw_text)
        else:
            raw = await request.body()
            raw_text = raw.decode("utf-8", errors="replace")
            body = _parse_wecom_xml(raw_text) if "<xml>" in raw_text else {}
    except Exception as exc:
        logger.warning("企微 webhook 解析失败: %s", exc)
        return "success"

    msg_type = body.get("MsgType", body.get("msgtype", ""))
    from_user = str(body.get("FromUserName", body.get("from_user_name", "")))
    content = str(body.get("Content", body.get("content", "")))
    agent_id = str(body.get("AgentID", body.get("agent_id", "")))

    if not content and msg_type == "event":
        # 事件消息，记录事件类型
        event = body.get("Event", body.get("event", ""))
        content = f"[事件: {event}]"

    if not content:
        return "success"

    # 写入 inbox
    push_inbox(
        channel_type="wework",
        contact_id=from_user,
        contact_name=from_user,
        direction="inbound",
        content=content,
        content_type="text",
        metadata={
            "msg_type": msg_type,
            "agent_id": agent_id,
            "msg_id": str(body.get("MsgId", body.get("msg_id", ""))),
        },
    )
    logger.info("企微 webhook 收到消息: from=%s, type=%s, content=%.100s", from_user, msg_type, content)

    # 企微要求返回 "success" 字符串
    return "success"


def _parse_wecom_xml(xml_text: str) -> dict:
    """简易企微 XML 解析（不依赖 lxml）。"""
    import re
    result: dict[str, str] = {}
    # 匹配 <Tag>value</Tag> 或 <Tag><![CDATA[value]]></Tag>
    pattern = re.compile(r"<(\w+)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</\1>", re.DOTALL)
    for match in pattern.finditer(xml_text):
        key, value = match.group(1), match.group(2).strip()
        result[key] = value
    return result
