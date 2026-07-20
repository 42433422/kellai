"""客来来 HTTP API（自 xcagi-customer-service-bridge user-cs 路由复制 · 独立前缀）。"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from typing import Annotated, Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
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
    "/api/kellai/auth/qr/start",
    "/api/kellai/auth/qr/status",
    "/api/kellai/auth/qr/scan",
    "/api/kellai/auth/qr/cancel",
    "/api/kellai/auth/xcmax-desktop",
    "/api/kellai/webhook/douyin",
    "/api/kellai/webhook/wechat",
    "/api/kellai/webhook/wework",
    "/api/kellai/webhook/wework/suite",
    "/api/kellai/channels/douyin/oauth/callback",
    "/api/kellai/channels/wework/customer-entry",
    "/api/kellai/channels/wechat/oauth/callback",
    "/api/kellai/channels/wechat/oauth/qrcode",
    "/api/kellai/channels/wework/oauth/callback",
    "/api/kellai/channels/wework/install/callback",
    "/api/kellai/internal/wework/readiness",
    "/api/kellai/internal/wework/install",
    "/api/kellai/internal/wework/install/status",
    "/api/kellai/internal/wework/customers/sync",
    "/api/kellai/internal/wework/customers",
    "/api/kellai/internal/wework/acquisition/members",
    "/api/kellai/internal/wework/acquisition/links",
    "/api/kellai/internal/douyin/readiness",
    "/api/kellai/internal/douyin/config",
    "/api/kellai/internal/douyin/oauth/initiate",
    "/api/kellai/internal/douyin/oauth/status",
    "/api/kellai/internal/douyin/connection",
    "/api/kellai/internal/douyin/messages/send",
    "/api/kellai/internal/douyin/inbox",
    "/api/kellai/internal/douyin/inbox/ack",
    "/api/kellai/integrations/xcmax/data-status",
    "/api/kellai/integrations/xcmax/customers",
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
    desktop_result: Optional[dict[str, Any]] = None
    auto_reply_inbound_id: str = Field(default="", max_length=512)


class DouyinBridgeSendBody(BaseModel):
    team_id: int = Field(..., gt=0)
    contact_id: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1, max_length=8000)
    persona_id: str = Field(default="", max_length=128)
    customer_id: int = Field(default=0, ge=0)
    reply_context: dict[str, Any] = Field(default_factory=dict)


class DouyinBridgeConfigBody(BaseModel):
    client_key: str = Field(default="", max_length=256)
    client_secret: str = Field(default="", max_length=1024)
    miniapp_app_id: str = Field(default="", max_length=256)
    miniapp_secret: str = Field(default="", max_length=1024)


class DouyinBridgeInboxAckBody(BaseModel):
    team_id: int = Field(..., gt=0)
    message_ids: list[str] = Field(default_factory=list, max_length=200)


class DouyinWebPortalConnectBody(BaseModel):
    token_or_url: str = Field(..., min_length=8, max_length=8192)


class DouyinWebPortalSyncBody(BaseModel):
    max_conversations: int = Field(default=200, ge=1, le=1000)
    history_limit: int = Field(default=20, ge=1, le=100)


class MarkReadBody(BaseModel):
    """标记已读 body。message_ids 优先；不传则按 customer_id 标记；都不传则全量。"""
    message_ids: list[str] = Field(default_factory=list, max_length=500)
    customer_id: Optional[int] = Field(default=None, gt=0)
    all: bool = False


class ChannelSyncInboxBody(BaseModel):
    """同步渠道收件箱到客户消息与漏斗闭环。"""
    channel_type: str = Field(default="", max_length=32)
    limit: int = Field(default=50, ge=1, le=200)
    # 仅供已验签 webhook 交给后台任务；普通请求仍由认证上下文校验。
    team_id: int = Field(default=0, ge=0, exclude=True)


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


class WorkforceHeartbeatBody(BaseModel):
    state: str = Field(default="online", max_length=16)


class WorkforceAssignBody(BaseModel):
    assignee_user_id: int = Field(..., gt=0)


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


class QrLoginBody(BaseModel):
    session_id: str = Field(..., min_length=16, max_length=128)
    secret: str = Field(default="", max_length=128)


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


class XcmaxAuthorizeBody(BaseModel):
    request_id: str = Field(min_length=12, max_length=128)
    authorization_secret: str = Field(min_length=24, max_length=256)
    accepted_scopes: list[str] = Field(default_factory=list, max_length=10)


class XcmaxCancelBody(BaseModel):
    request_id: str = Field(min_length=12, max_length=128)
    authorization_secret: str = Field(min_length=24, max_length=256)


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


class AutoReplyClaimBody(BaseModel):
    limit: int = Field(default=3, ge=1, le=10)


class AutoReplyResultBody(BaseModel):
    inbound_message_id: str = Field(..., min_length=1, max_length=512)
    success: bool
    error: str = Field(default="", max_length=2000)
    outbound_message_id: str = Field(default="", max_length=512)


class ScoreBody(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    market_user_id: Optional[int] = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# 渠道统一 API
# ---------------------------------------------------------------------------


CHANNEL_ONBOARDING_GUIDES: dict[str, dict[str, Any]] = {
    "wechat": {
        "recommended_mode": "scan",
        "auth_modes": ["scan", "form"],
        "required_fields": ["app_id", "app_secret"],
        "optional_fields": ["official_app_id", "official_app_secret", "token", "encoding_aes_key", "bot_webhook"],
        "materials": ["微信开放平台网站应用", "已审核通过的 AppID / AppSecret", "微信开放平台授权回调域名", "公众号 AppID / Secret（如需客服消息）"],
        "external_steps": ["在微信开放平台创建并审核网站应用", "把授权回调域名配置为当前客来来公网域名", "回填 AppID / AppSecret 后扫码授权", "如需接收公众号消息，在公众平台配置 /api/kellai/webhook/wechat"],
        "success_criteria": ["扫码授权后能保存 openid/unionid", "微信回调消息能进入统一收件箱", "同步收件箱后客户自动进入漏斗"],
    },
    "wework": {
        "recommended_mode": "scan",
        "auth_modes": ["scan", "form"],
        "required_fields": [],
        "optional_fields": ["corp_id", "secret", "agent_id", "bot_webhook", "kf_url", "open_kfid"],
        "materials": ["企业微信管理员权限", "客来来服务商第三方应用", "公网 HTTPS 指令回调与安装回调"],
        "external_steps": ["客来来服务商后台创建 SaaS 第三方应用", "配置客户联系权限和公网回调", "管理员扫描客来来安装二维码并确认授权", "自动同步外部联系人"],
        "success_criteria": ["企业安装授权成功", "真实外部联系人能同步到客来来客户列表", "客户自动进入漏斗并生成下一步动作"],
    },
    "douyin": {
        "recommended_mode": "scan",
        "auth_modes": ["scan", "form"],
        "required_fields": ["app_id", "app_secret", "miniapp_app_id", "miniapp_secret"],
        "optional_fields": ["client_key", "client_secret"],
        "materials": [
            "抖音开放平台移动/网站应用 Client Key / Client Secret",
            "抖音小程序 AppID",
            "小程序“开发配置 → Webhooks”中的 Webhook AppSecret",
            "已认证企业号或小程序品牌号/员工号",
            "公网 HTTPS Webhook 地址",
        ],
        "external_steps": [
            "移动/网站应用仅用于测试白名单和基础账号授权",
            "在小程序“关联设置 → 抖音号管理”为经营号开通小程序发送私信能力",
            "把客来来 Webhook 地址配置到小程序，并订阅 im_send_msg、im_receive_msg、im_enter_direct_msg",
            "回填小程序 AppID 与 Webhook AppSecret；真实私信到达后即可在客来来回复",
        ],
        "success_criteria": [
            "Webhook 验签通过且真实私信自动建立客户与会话",
            "客来来使用 BusinessToken 调用 /im/send/msg/ 回复成功",
            "发送回执不重复入库且消息驱动统一接待与漏斗",
        ],
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
    if channel_type == "douyin" and str(config.get("remote_credentials_configured") or "").lower() == "true":
        missing_required = [
            key
            for key in missing_required
            if key not in {"app_id", "app_secret", "client_key", "client_secret"}
        ]
    if channel_type == "douyin" and str(config.get("remote_miniapp_configured") or "").lower() == "true":
        missing_required = [
            key
            for key in missing_required
            if key not in {"miniapp_app_id", "miniapp_secret"}
        ]
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
async def list_channels(request: Request = None):
    """列出所有已注册渠道及状态（含已保存的配置）。"""
    from app.channels import ChannelRegistry
    from app.channels.config_store import get_all
    from app.channels.config_store import save as save_config

    reg = ChannelRegistry()
    channels = reg.list_channels()
    user = get_request_user(request) if request is not None else None
    team_id = int((user or {}).get("team_id") or 0)
    result = []
    for ch in channels:
        cfg = get_all(ch["channel_type"])
        merged_config = dict(cfg.get("config") or {})
        has_config = any(str(v).strip() for v in merged_config.values())
        enabled = bool(cfg.get("enabled", has_config))
        connected = enabled and bool(cfg.get("connected"))
        connection_message = ""
        if ch["channel_type"] == "douyin" and team_id > 0:
            try:
                from app.services.douyin_channel import (
                    remote_bridge_enabled,
                    remote_connection_status,
                )

                if remote_bridge_enabled():
                    remote_status = await remote_connection_status(team_id)
                    connected = bool(remote_status.get("connected"))
                    connection_message = str(remote_status.get("message") or "")
                    authorization = remote_status.get("authorization")
                    if isinstance(authorization, dict) and authorization.get("open_id"):
                        merged_config.update(
                            {
                                "oauth_authorized": "true",
                                "oauth_scope": str(authorization.get("scope") or ""),
                                "direct_message_enabled": str(
                                    bool((remote_status.get("capabilities") or {}).get("direct_message"))
                                ).lower(),
                            }
                        )
                        has_config = True
                        enabled = True
                    miniapp = remote_status.get("miniapp")
                    if isinstance(miniapp, dict) and miniapp.get("app_id_configured"):
                        merged_config.update(
                            {
                                "miniapp_app_id": str(miniapp.get("app_id") or ""),
                                "remote_miniapp_configured": str(
                                    bool(miniapp.get("webhook_secret_configured"))
                                ).lower(),
                            }
                        )
                        has_config = True
                        enabled = True
                    if connected != bool(cfg.get("connected")):
                        cfg = save_config(
                            "douyin",
                            {},
                            enabled=enabled or connected,
                            connected=connected,
                        )
                        enabled = bool(cfg.get("enabled"))
            except Exception as exc:
                logger.warning("刷新抖音远端授权状态失败: %s", exc)
            try:
                from app.services.douyin_web_portal import status as web_portal_status

                web_state = web_portal_status(team_id)
                if web_state.get("connected"):
                    connected = True
                    enabled = True
                    has_config = True
                    merged_config.update(
                        {
                            "web_portal_connected": "true",
                            "web_portal_monitor_running": str(
                                bool(web_state.get("monitor_running"))
                            ).lower(),
                            "web_portal_contact_count": str(
                                int(web_state.get("contact_count") or 0)
                            ),
                        }
                    )
                    account_name = str(web_state.get("account_name") or "").strip()
                    connection_message = (
                        f"抖音网站数据已连接：{account_name}"
                        if account_name
                        else "抖音网站数据已连接"
                    )
                    if not bool(cfg.get("connected")) or not bool(cfg.get("enabled")):
                        cfg = save_config(
                            "douyin",
                            {"web_portal_connected": "true"},
                            enabled=True,
                            connected=True,
                        )
                elif "web_portal_connected" in merged_config:
                    merged_config["web_portal_connected"] = "false"
            except Exception as exc:
                logger.warning("刷新抖音网站数据连接状态失败: %s", exc)
        result.append({
            "id": f"ch_{ch['channel_type']}",
            "name": cfg.get("name") or ch["channel_type"],
            "type": ch["channel_type"],
            "adapter_class": ch["adapter_class"],
            "enabled": enabled,
            "connected": connected,
            "message": (
                connection_message
                or ("已连接" if connected else ("已保存配置，点击测试连接验证" if has_config else "未配置"))
            ),
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
async def test_channel(channel_type: str, request: Request = None):
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
        user = get_request_user(request) if request is not None else None
        team_id = int((user or {}).get("team_id") or 0)
        if channel_type == "douyin" and team_id > 0:
            from app.services.douyin_web_portal import status as web_portal_status

            web_state = web_portal_status(team_id)
            if web_state.get("connected"):
                account_name = str(web_state.get("account_name") or "").strip()
                result = {
                    "connected": True,
                    "source": "douyin_web_portal",
                    "message": (
                        f"抖音网站数据已连接：{account_name}"
                        if account_name
                        else "抖音网站数据已连接"
                    ),
                }
            else:
                result = await adapter.test_connection(team_id=team_id)
        else:
            result = await adapter.test_connection(team_id=team_id)
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

    config_to_save = dict(body.config)
    if channel_type == "douyin":
        from app.services.douyin_channel import (
            DouyinChannelError,
            remote_bridge_enabled,
            remote_save_app_config,
        )

        next_client_key = str(
            config_to_save.get("client_key")
            or config_to_save.get("app_id")
            or ""
        ).strip()
        next_client_secret = str(
            config_to_save.get("client_secret")
            or config_to_save.get("app_secret")
            or ""
        ).strip()
        next_miniapp_app_id = str(
            config_to_save.get("miniapp_app_id")
            or config_to_save.get("miniapp_appid")
            or ""
        ).strip()
        next_miniapp_secret = str(
            config_to_save.get("miniapp_secret")
            or config_to_save.get("miniapp_app_secret")
            or ""
        ).strip()
        if remote_bridge_enabled():
            try:
                remote_state = await remote_save_app_config(
                    next_client_key=next_client_key,
                    next_client_secret=next_client_secret,
                    next_miniapp_app_id=next_miniapp_app_id,
                    next_miniapp_secret=next_miniapp_secret,
                )
            except DouyinChannelError as exc:
                raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
            config_to_save = {
                "app_id": str(remote_state.get("client_key") or next_client_key),
                "app_secret": "",
                "client_key": str(remote_state.get("client_key") or next_client_key),
                "client_secret": "",
                "miniapp_app_id": str(
                    remote_state.get("miniapp_app_id") or next_miniapp_app_id
                ),
                "miniapp_secret": "",
                "remote_credentials_configured": "true",
                "remote_miniapp_configured": (
                    "true" if remote_state.get("miniapp_secret_configured") else "false"
                ),
            }
        else:
            try:
                from app.services.douyin_channel import save_app_config_verified

                local_state = await save_app_config_verified(
                    next_client_key=next_client_key,
                    next_client_secret=next_client_secret,
                    next_miniapp_app_id=next_miniapp_app_id,
                    next_miniapp_secret=next_miniapp_secret,
                )
            except DouyinChannelError as exc:
                raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
            config_to_save = {
                "app_id": str(local_state.get("client_key") or next_client_key),
                "app_secret": "",
                "client_key": str(local_state.get("client_key") or next_client_key),
                "client_secret": "",
                "miniapp_app_id": str(
                    local_state.get("miniapp_app_id") or next_miniapp_app_id
                ),
                "miniapp_secret": "",
                "remote_credentials_configured": "true",
                "remote_miniapp_configured": (
                    "true" if local_state.get("miniapp_secret_configured") else "false"
                ),
            }

    saved = save_config(
        channel_type,
        config_to_save,
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
async def sync_channel_inbox(body: ChannelSyncInboxBody, request: Request = None):
    """消费渠道收件箱，落库为客户消息，并驱动客户/漏斗/待办闭环。"""
    from app.channels import ChannelRegistry
    from app.services.message_store import mark_inbox_consumed, save_message

    reg = ChannelRegistry()
    if body.channel_type.strip():
        channel_types = [body.channel_type.strip()]
    else:
        channel_types = [c["channel_type"] for c in reg.list_channels()]

    saved_messages: list[dict[str, Any]] = []
    local_consumed_ids: list[str] = []
    remote_douyin_ids: list[str] = []
    auto_reply_queued = 0
    seen_ids: set[str] = set()
    errors: list[dict[str, str]] = []
    user = get_request_user(request) if request is not None else None
    from app.services.tenant_context import resolve_team_id

    team_id = resolve_team_id(
        int((user or {}).get("team_id") or body.team_id or 0)
    )

    for channel_type in channel_types:
        remote_douyin = False
        try:
            adapter = reg.get(channel_type)
        except KeyError as exc:
            errors.append({"channel_type": channel_type, "error": str(exc)})
            continue
        try:
            if channel_type == "douyin":
                from app.services.douyin_channel import remote_bridge_enabled

                remote_douyin = remote_bridge_enabled()
                messages = await adapter.receive_messages(limit=body.limit, team_id=team_id)
            else:
                messages = await adapter.receive_messages(limit=body.limit)
        except Exception as exc:
            logger.warning("同步渠道收件箱失败: channel=%s", channel_type, exc_info=True)
            errors.append({"channel_type": channel_type, "error": str(exc)})
            continue
        for msg in messages:
            if msg.id in seen_ids:
                continue
            seen_ids.add(msg.id)
            try:
                saved = save_message(msg)
            except Exception as exc:
                logger.warning(
                    "渠道消息落库失败: channel=%s message_id=%s",
                    channel_type,
                    msg.id,
                    exc_info=True,
                )
                errors.append(
                    {
                        "channel_type": channel_type,
                        "error": f"消息 {msg.id} 落库失败: {exc}",
                    }
                )
                continue
            if remote_douyin:
                remote_douyin_ids.append(msg.id)
            else:
                local_consumed_ids.append(msg.id)
            saved_messages.append(saved.model_dump())
            try:
                from app.services.auto_reply_runtime import enqueue_message

                if enqueue_message(saved):
                    auto_reply_queued += 1
            except Exception:
                logger.warning(
                    "入站消息已保存但自动回复任务入队失败: message_id=%s",
                    msg.id,
                    exc_info=True,
                )

    consumed = mark_inbox_consumed(local_consumed_ids, team_id=team_id)
    if remote_douyin_ids:
        try:
            from app.services.douyin_channel import remote_ack_inbox

            consumed += await remote_ack_inbox(team_id, remote_douyin_ids)
        except Exception as exc:
            logger.warning("确认远端抖音收件箱消费状态失败", exc_info=True)
            errors.append(
                {
                    "channel_type": "douyin",
                    "error": f"消息已落库，但远端消费确认失败，将在下次同步时重试: {exc}",
                }
            )
    return {
        "success": True,
        "data": {
            "synced": len(saved_messages),
            "consumed": consumed,
            "messages": saved_messages,
            "auto_reply_queued": auto_reply_queued,
            "errors": errors,
        },
    }


# ---------------------------------------------------------------------------
# 抖音企业号 OAuth 与 Webhook
# ---------------------------------------------------------------------------


def _douyin_web_team_id(current_user: dict) -> int:
    team_id = int(current_user.get("team_id") or 0)
    if team_id <= 0:
        raise HTTPException(status_code=400, detail={"message": "当前账号尚未加入团队"})
    return team_id


@router.get("/channels/douyin/web-portal/status")
async def douyin_web_portal_status(current_user: CurrentUser):
    """抖音网站 Token 连接、同步与实时监控状态。"""
    from app.services.douyin_web_portal import status

    return {"success": True, "data": status(_douyin_web_team_id(current_user))}


@router.post("/channels/douyin/web-portal/connect")
async def douyin_web_portal_connect(
    body: DouyinWebPortalConnectBody,
    current_user: CurrentUser,
):
    """保存用户主动提供的网站 token，并验证数据连接。"""
    from app.services.douyin_web_portal import DouyinWebPortalError, connect

    team_id = _douyin_web_team_id(current_user)
    try:
        data = await connect(team_id, body.token_or_url)
    except DouyinWebPortalError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    return {"success": True, "data": data}


@router.delete("/channels/douyin/web-portal")
async def douyin_web_portal_disconnect(current_user: CurrentUser):
    """删除本团队保存的第三方客服网页令牌与联系人缓存。"""
    from app.services.douyin_web_portal import disconnect, stop_monitor

    team_id = _douyin_web_team_id(current_user)
    await stop_monitor(team_id)
    return {"success": True, "data": {"disconnected": disconnect(team_id)}}


@router.post("/channels/douyin/web-portal/sync")
async def douyin_web_portal_sync(
    body: DouyinWebPortalSyncBody,
    current_user: CurrentUser,
):
    """同步第三方客服网页中的抖音账号、客户会话和历史消息。"""
    from app.services.douyin_web_portal import DouyinWebPortalError, sync_messages

    team_id = _douyin_web_team_id(current_user)
    try:
        data = await sync_messages(
            team_id,
            max_conversations=body.max_conversations,
            history_limit=body.history_limit,
        )
    except DouyinWebPortalError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    return {"success": True, "data": data}


@router.post("/channels/douyin/web-portal/monitor/start")
async def douyin_web_portal_monitor_start(current_user: CurrentUser):
    """连接第三方工作台 WebSocket，实时把新私信写入客来来。"""
    from app.services.douyin_web_portal import DouyinWebPortalError, start_monitor

    try:
        data = await start_monitor(_douyin_web_team_id(current_user))
    except DouyinWebPortalError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    return {"success": True, "data": data}


@router.post("/channels/douyin/web-portal/monitor/stop")
async def douyin_web_portal_monitor_stop(current_user: CurrentUser):
    """停止第三方工作台实时私信连接。"""
    from app.services.douyin_web_portal import stop_monitor

    return {
        "success": True,
        "data": await stop_monitor(_douyin_web_team_id(current_user)),
    }


@router.get("/channels/douyin/web-portal/contacts")
async def douyin_web_portal_contacts(
    current_user: CurrentUser,
    limit: int = 500,
):
    """返回已同步的网站联系人及列表中的最新消息。"""
    from app.services.douyin_web_portal import list_contacts

    return {
        "success": True,
        "data": list_contacts(
            _douyin_web_team_id(current_user),
            max(1, min(int(limit), 1000)),
        ),
    }


@router.get("/channels/douyin/web-portal/stream")
async def douyin_web_portal_stream(current_user: CurrentUser):
    """以 NDJSON 流式返回第三方网页连接与消息同步状态。"""
    from app.services.douyin_web_portal import stream_status

    return StreamingResponse(
        stream_status(_douyin_web_team_id(current_user)),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/channels/douyin/readiness")
async def douyin_readiness(current_user: CurrentUser):
    """返回抖音开放平台应用、OAuth 回调与 Webhook 的配置状态。"""
    from app.services.douyin_channel import (
        DouyinChannelError,
        readiness,
        remote_bridge_enabled,
        remote_readiness,
    )

    _ = current_user
    try:
        data = await remote_readiness() if remote_bridge_enabled() else readiness()
    except DouyinChannelError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.post("/channels/douyin/oauth/initiate")
async def douyin_oauth_initiate(current_user: CurrentUser):
    """为当前客来来团队生成抖音企业号扫码授权地址。"""
    from app.services.douyin_channel import (
        DouyinChannelError,
        create_oauth_url,
        remote_bridge_enabled,
        remote_create_oauth_url,
        validate_app_credentials,
    )

    try:
        args = {
            "team_id": int(current_user.get("team_id") or 0),
            "user_id": int(current_user.get("id") or 0),
        }
        if remote_bridge_enabled():
            data = await remote_create_oauth_url(**args)
        else:
            await validate_app_credentials()
            data = create_oauth_url(**args)
    except DouyinChannelError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.get("/channels/douyin/oauth/callback")
async def douyin_oauth_callback(
    state: str = "",
    code: str = "",
    error: str = "",
    error_description: str = "",
):
    """抖音企业号扫码确认后的公网 OAuth 回调。"""
    import html

    from fastapi.responses import HTMLResponse

    # 测试应用白名单授权需要让指定抖音号完成
    # user_info + trial.whitelist 授权。该流程不落盘短期 code，也不要求
    # 桌面端提前创建普通 OAuth session，避免白名单扫码完成后被误报 state 失效。
    if state.startswith("trial-whitelist-"):
        if error or not code:
            message = error_description or error or "用户取消授权"
            return HTMLResponse(
                "<html><body style='font-family:sans-serif;padding:32px'>"
                f"<h3>测试白名单授权未完成：{html.escape(message)}</h3>"
                "<p>请返回授权二维码页面后重新扫码。</p>"
                "</body></html>",
                status_code=400,
            )
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:32px'>"
            "<h3>测试白名单授权已完成</h3>"
            "<p>当前抖音号已同意授予 user_info 与 trial.whitelist 权限。"
            "请关闭此页面并返回抖音开放平台查看白名单状态。</p>"
            "</body></html>"
        )

    from app.services.douyin_channel import (
        DouyinChannelError,
        complete_oauth,
        fail_oauth,
    )

    if not state:
        return HTMLResponse("<h3>抖音授权失败：缺少 state</h3>", status_code=400)
    if error or not code:
        message = error_description or error or "用户取消授权"
        fail_oauth(state, message)
        return HTMLResponse(
            f"<h3>抖音授权未完成：{html.escape(message)}</h3>",
            status_code=400,
        )
    try:
        result = await complete_oauth(state=state, code=code)
    except DouyinChannelError as exc:
        logger.warning("抖音 OAuth 回调失败: %s", exc)
        return HTMLResponse(
            f"<h3>抖音授权失败：{html.escape(str(exc))}</h3>",
            status_code=400,
        )
    account = html.escape(str(result.get("nickname") or result.get("open_id") or "企业号"))
    return HTMLResponse(
        "<html><body>"
        f"<h3>抖音企业号 {account} 已成功绑定客来来</h3>"
        "<p>可以关闭此页面并返回客来来，真实私信将通过 Webhook 自动进入客户列表。</p>"
        "<script>setTimeout(() => window.close(), 1200);</script>"
        "</body></html>"
    )


@router.get("/channels/douyin/oauth/status")
async def douyin_oauth_status(state: str, current_user: CurrentUser):
    """桌面端轮询当前团队的抖音企业号授权状态。"""
    from app.services.douyin_channel import (
        DouyinChannelError,
        get_oauth_status,
        remote_bridge_enabled,
        remote_oauth_status,
    )

    try:
        args = {"state": state, "team_id": int(current_user.get("team_id") or 0)}
        data = (
            await remote_oauth_status(**args)
            if remote_bridge_enabled()
            else get_oauth_status(**args)
        )
    except DouyinChannelError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


def _verify_douyin_bridge(request: Request) -> None:
    from app.services.douyin_channel import DouyinChannelError, verify_bridge_key

    try:
        verify_bridge_key(request.headers.get("X-Kellai-Douyin-Bridge-Key", ""))
    except DouyinChannelError as exc:
        raise HTTPException(status_code=401, detail={"message": str(exc)}) from exc


@router.get("/internal/douyin/readiness")
async def internal_douyin_readiness(request: Request):
    from app.services.douyin_channel import readiness

    _verify_douyin_bridge(request)
    return {"success": True, "data": readiness()}


@router.put("/internal/douyin/config")
async def internal_douyin_config(request: Request, body: DouyinBridgeConfigBody):
    from app.services.douyin_channel import DouyinChannelError, save_app_config_verified

    _verify_douyin_bridge(request)
    try:
        data = await save_app_config_verified(
            next_client_key=body.client_key,
            next_client_secret=body.client_secret,
            next_miniapp_app_id=body.miniapp_app_id,
            next_miniapp_secret=body.miniapp_secret,
        )
    except DouyinChannelError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.post("/internal/douyin/oauth/initiate")
async def internal_douyin_oauth_initiate(request: Request, team_id: int, user_id: int):
    from app.services.douyin_channel import (
        DouyinChannelError,
        create_oauth_url,
        validate_app_credentials,
    )

    _verify_douyin_bridge(request)
    try:
        await validate_app_credentials()
        data = create_oauth_url(team_id=int(team_id), user_id=int(user_id))
    except DouyinChannelError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.get("/internal/douyin/oauth/status")
async def internal_douyin_oauth_status(request: Request, state: str, team_id: int):
    from app.services.douyin_channel import DouyinChannelError, get_oauth_status

    _verify_douyin_bridge(request)
    try:
        data = get_oauth_status(state=state, team_id=int(team_id))
    except DouyinChannelError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.get("/internal/douyin/connection")
async def internal_douyin_connection(request: Request, team_id: int):
    from app.services.douyin_channel import DouyinChannelError, connection_status

    _verify_douyin_bridge(request)
    try:
        data = await connection_status(int(team_id))
    except DouyinChannelError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.post("/internal/douyin/messages/send")
async def internal_douyin_send(request: Request, body: DouyinBridgeSendBody):
    from app.channels.douyin import DouyinAdapter

    _verify_douyin_bridge(request)
    result = await DouyinAdapter().send_message(
        body.contact_id,
        body.content,
        team_id=body.team_id,
        persona_id=body.persona_id,
        customer_id=body.customer_id,
        reply_context=body.reply_context,
    )
    if not result.get("success"):
        return {"success": False, "error": result.get("error") or "抖音消息发送失败"}
    return {"success": True, "data": result}


@router.get("/internal/douyin/inbox")
async def internal_douyin_inbox(request: Request, team_id: int, limit: int = 50):
    from app.services.douyin_channel import pull_team_inbox

    _verify_douyin_bridge(request)
    rows = pull_team_inbox(int(team_id), limit=max(1, min(int(limit), 200)))
    return {"success": True, "data": {"messages": rows, "total": len(rows)}}


@router.post("/internal/douyin/inbox/ack")
async def internal_douyin_inbox_ack(request: Request, body: DouyinBridgeInboxAckBody):
    from app.services.douyin_channel import ack_team_inbox

    _verify_douyin_bridge(request)
    consumed = ack_team_inbox(body.team_id, body.message_ids)
    return {"success": True, "data": {"consumed": consumed}}


def _douyin_pick_str(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _douyin_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip().startswith("{"):
        import json

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _douyin_nested_message(content: dict[str, Any]) -> dict[str, Any]:
    for key in ("message", "msg", "msg_content", "message_content", "body", "data", "content"):
        nested = _douyin_dict(content.get(key))
        if nested:
            return nested
    return {}


def _douyin_user_info_items(content: dict[str, Any]) -> list[dict[str, Any]]:
    values = []
    for key in ("user_infos", "user_info", "users", "members"):
        value = content.get(key)
        if isinstance(value, list):
            values.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            values.append(value)
    for key in ("customer", "sender", "from_user"):
        value = content.get(key)
        if isinstance(value, dict):
            values.append(value)
    return values


def _douyin_user_identity(item: dict[str, Any]) -> str:
    return _douyin_pick_str(
        item.get("open_id"),
        item.get("openid"),
        item.get("c_open_id"),
        item.get("from_open_id"),
        item.get("user_open_id"),
        item.get("id"),
    )


def _douyin_contact_name(content: dict[str, Any], contact_id: str) -> str:
    for item in _douyin_user_info_items(content):
        if _douyin_user_identity(item) == contact_id:
            return _douyin_pick_str(
                item.get("nick_name"),
                item.get("nickname"),
                item.get("name"),
                item.get("display_name"),
            )
    return _douyin_pick_str(content.get("nick_name"), content.get("nickname"))


def _douyin_group_name(content: dict[str, Any], group_id: str) -> str:
    group_info = content.get("group_info")
    if isinstance(group_info, dict):
        for key in ("group_name", "name", "title"):
            value = str(group_info.get(key) or "").strip()
            if value:
                return value
    suffix = group_id[-8:] if group_id else ""
    return f"抖音粉丝群{('·' + suffix) if suffix else ''}"


def _douyin_payload_app_id(payload: dict[str, Any], content: dict[str, Any]) -> str:
    return _douyin_pick_str(
        payload.get("app_id"),
        payload.get("appid"),
        payload.get("client_key"),
        content.get("app_id"),
        content.get("appid"),
        content.get("client_key"),
    )


def _douyin_event_actor_ids(payload: dict[str, Any], content: dict[str, Any]) -> tuple[str, str]:
    nested = _douyin_nested_message(content)
    from_user_id = _douyin_pick_str(
        payload.get("from_user_id"),
        payload.get("from_open_id"),
        payload.get("sender_open_id"),
        payload.get("sender"),
        content.get("from_user_id"),
        content.get("from_open_id"),
        content.get("sender_open_id"),
        content.get("sender"),
        nested.get("from_user_id"),
        nested.get("from_open_id"),
        nested.get("sender_open_id"),
        content.get("c_open_id"),
        content.get("open_id"),
        nested.get("c_open_id"),
        nested.get("open_id"),
    )
    to_user_id = _douyin_pick_str(
        payload.get("to_user_id"),
        payload.get("to_open_id"),
        payload.get("receiver_open_id"),
        payload.get("receiver"),
        content.get("to_user_id"),
        content.get("to_open_id"),
        content.get("receiver_open_id"),
        content.get("receiver"),
        content.get("owner_open_id"),
        content.get("account_open_id"),
        nested.get("to_user_id"),
        nested.get("to_open_id"),
        nested.get("receiver_open_id"),
        nested.get("owner_open_id"),
    )
    return from_user_id, to_user_id


def _douyin_participant_ids(payload: dict[str, Any], content: dict[str, Any]) -> list[str]:
    nested = _douyin_nested_message(content)
    candidates = [
        payload.get("open_id"),
        payload.get("openid"),
        payload.get("c_open_id"),
        payload.get("from_user_id"),
        payload.get("to_user_id"),
        content.get("open_id"),
        content.get("openid"),
        content.get("c_open_id"),
        content.get("from_user_id"),
        content.get("to_user_id"),
        nested.get("open_id"),
        nested.get("openid"),
        nested.get("c_open_id"),
        nested.get("from_user_id"),
        nested.get("to_user_id"),
    ]
    candidates.extend(_douyin_user_identity(item) for item in _douyin_user_info_items(content))
    cleaned = [_douyin_pick_str(value) for value in candidates]
    return list(dict.fromkeys(value for value in cleaned if value))


def _douyin_message_id(payload: dict[str, Any], content: dict[str, Any], request: Request) -> str:
    nested = _douyin_nested_message(content)
    return _douyin_pick_str(
        content.get("server_message_id"),
        content.get("message_id"),
        content.get("msg_id"),
        nested.get("server_message_id"),
        nested.get("message_id"),
        nested.get("msg_id"),
        payload.get("server_message_id"),
        payload.get("message_id"),
        payload.get("msg_id"),
        request.headers.get("Msg-Id"),
    )


def _douyin_message_text(event: str, content: dict[str, Any]) -> tuple[str, str]:
    nested = _douyin_nested_message(content)
    message_type = _douyin_pick_str(
        content.get("message_type"),
        content.get("msg_type"),
        nested.get("message_type"),
        nested.get("msg_type"),
        "text",
    )
    text = _douyin_pick_str(
        content.get("text"),
        content.get("message_text"),
        content.get("msg_text"),
        nested.get("text"),
        nested.get("message_text"),
        nested.get("msg_text"),
        nested.get("content"),
        content.get("content"),
    )
    if message_type == "text":
        return text, "text"
    if message_type == "retain_consult_card":
        rows = content.get("card_data")
        values: list[str] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label") or "").strip()
                value = str(row.get("value") or "").strip()
                if label and value:
                    values.append(f"{label}：{value}")
        summary = "；".join(values)
        return (
            f"[抖音留资卡已提交]{' ' + summary if summary else ''}",
            "lead",
        )
    if event in {"im_enter_direct_msg", "enter_im", "authorize_private_message", "im_authorize"}:
        return "[客户进入抖音私信会话]", "event"
    if event == "group_fans_event":
        return "[客户加入抖音粉丝群]", "event"
    if text:
        return text, message_type
    return f"[抖音{message_type}消息]", message_type


@router.post("/webhook/douyin")
async def douyin_webhook_receive(request: Request, background_tasks: BackgroundTasks):
    """接收抖音开放平台事件，验签、去重并自动进入客来来消息闭环。"""
    import json

    from fastapi.responses import PlainTextResponse

    from app.services.douyin_channel import (
        client_key,
        bridge_server_enabled,
        default_team_for_miniapp_event,
        find_authorization_for_event,
        miniapp_app_id,
        parse_event_content,
        revoke_authorization,
        verify_webhook_signature,
    )
    from app.services.message_store import push_inbox

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail={"message": "抖音 Webhook JSON 无效"}) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail={"message": "抖音 Webhook 数据格式无效"})

    event = str(payload.get("event") or "")
    content = parse_event_content(payload.get("content"))
    if event == "verify_webhook":
        challenge = content.get("challenge")
        return PlainTextResponse(
            json.dumps({"challenge": challenge}, ensure_ascii=False, separators=(",", ":")),
            media_type="application/json",
        )

    signature = request.headers.get("X-Douyin-Signature", "")
    if not verify_webhook_signature(raw_body, signature):
        logger.warning("抖音 Webhook 验签失败")
        raise HTTPException(status_code=401, detail={"message": "抖音 Webhook 验签失败"})

    event_app_id = _douyin_payload_app_id(payload, content)
    configured_client_key = client_key()
    configured_miniapp_app_id = miniapp_app_id()
    looks_like_miniapp_app_id = event_app_id.startswith("tt")
    if (
        event_app_id
        and event_app_id != configured_client_key
        and event_app_id != configured_miniapp_app_id
        and (configured_miniapp_app_id or not looks_like_miniapp_app_id)
    ):
        raise HTTPException(status_code=401, detail={"message": "抖音 Webhook Client Key 不匹配"})

    from_user_id, to_user_id = _douyin_event_actor_ids(payload, content)
    participant_ids = _douyin_participant_ids(payload, content)
    auth = find_authorization_for_event(from_user_id, to_user_id, *participant_ids)
    team_id = int(auth["team_id"]) if auth else default_team_for_miniapp_event(event_app_id)

    if event in {"unauthorize", "contract_unauthorize"}:
        revoked = revoke_authorization(
            team_id=int(auth["team_id"]) if auth else None,
            open_id=from_user_id if auth is None else "",
        )
        if revoked:
            from app.channels.config_store import save as save_channel_config

            save_channel_config("douyin", {}, connected=False)
        return {"success": True, "data": {"event": event, "revoked": revoked}}

    supported_events = {
        "receive_msg",
        "im_receive_msg",
        "im_send_msg",
        "enter_im",
        "im_enter_direct_msg",
        "im_group_receive_msg",
        "im_group_send_msg",
        "group_fans_event",
        "customer_service_message",
        "customer_service_receive_msg",
        "ma_others_im_message",
        "authorize_private_message",
        "im_authorize",
    }
    if event not in supported_events:
        return {"success": True, "data": {"event": event, "ignored": True}}
    if team_id is None:
        logger.warning(
            "抖音 Webhook 未匹配到已授权团队: event=%s app_id=%s from=%s to=%s",
            event,
            event_app_id,
            from_user_id,
            to_user_id,
        )
        return {"success": True, "data": {"event": event, "ignored": True, "reason": "unknown_account"}}

    own_open_id = str(auth["open_id"]) if auth else _douyin_pick_str(to_user_id, event_app_id)
    direction = "outbound" if from_user_id == own_open_id else "inbound"
    is_group = event in {"im_group_receive_msg", "im_group_send_msg", "group_fans_event"}
    conversation_id = _douyin_pick_str(
        content.get("conversation_short_id")
        or content.get("conversation_id")
        or content.get("session_id")
        or content.get("im_group_id")
        or payload.get("conversation_id")
    )
    if is_group and conversation_id:
        contact_id = f"group:{conversation_id}"
        contact_name = _douyin_group_name(content, conversation_id)
    else:
        contact_id = to_user_id if direction == "outbound" else from_user_id
        if not contact_id:
            contact_id = _douyin_pick_str(
                from_user_id,
                to_user_id,
                content.get("c_open_id"),
                content.get("open_id"),
                conversation_id,
            )
        if not contact_id:
            contact_id = f"anonymous:{_douyin_message_id(payload, content, request) or event_app_id or event}"
        contact_name = _douyin_contact_name(content, contact_id)
    source = str(content.get("source") or "")
    if direction == "outbound" and source in {client_key(), miniapp_app_id()}:
        # API 发出的消息已经由 /messages/send 落库，跳过平台确认事件避免重复。
        return {"success": True, "data": {"event": event, "ignored": True, "reason": "api_echo"}}

    message_text, content_type = _douyin_message_text(event, content)
    server_message_id = _douyin_message_id(payload, content, request)
    dedupe_id = f"douyin:{server_message_id}" if server_message_id else None
    metadata = {
        "source": "douyin_webhook",
        "event": event,
        "team_id": int(team_id),
        "owner_open_id": own_open_id,
        "miniapp_app_id": event_app_id,
        "conversation_id": conversation_id,
        "is_group": is_group,
        "sender_open_id": from_user_id,
        "sender_name": _douyin_contact_name(content, from_user_id),
        "server_message_id": server_message_id,
        "message_index": str(content.get("index") or ""),
        "event_content": content,
    }
    inbox_id = push_inbox(
        "douyin",
        contact_id=contact_id,
        contact_name=contact_name,
        direction=direction,
        content=message_text,
        content_type=content_type,
        metadata=metadata,
        msg_id=dedupe_id,
    )
    if not bridge_server_enabled():
        background_tasks.add_task(
            sync_channel_inbox,
            ChannelSyncInboxBody(channel_type="douyin", limit=50, team_id=int(team_id)),
        )
    return {
        "success": True,
        "data": {
            "event": event,
            "message_id": inbox_id,
            "direction": direction,
            "queued": True,
        },
    }


# ---------------------------------------------------------------------------
# 微信开放平台 OAuth 端点
# ---------------------------------------------------------------------------

_wechat_oauth_states: dict[str, float] = {}
_wechat_oauth_results: dict[str, dict[str, Any]] = {}
_wechat_oauth_sessions: dict[str, dict[str, Any]] = {}


def _wechat_cfg(field: str) -> str:
    from app.channels.config_store import get_field

    return get_field("wechat", field) or os.environ.get(f"KELLAI_WECHAT_{field.upper()}", "").strip()


def _wechat_app_id() -> str:
    return _wechat_cfg("app_id") or _wechat_cfg("appid")


def _wechat_app_secret() -> str:
    return _wechat_cfg("app_secret") or _wechat_cfg("secret") or _wechat_cfg("appsecret")


def _build_wechat_oauth_url(request: Request, state: str) -> str:
    from urllib.parse import quote_plus

    redirect_uri = str(request.base_url).rstrip("/") + "/api/kellai/channels/wechat/oauth/callback"
    return (
        "https://open.weixin.qq.com/connect/qrconnect"
        f"?appid={_wechat_app_id()}"
        f"&redirect_uri={quote_plus(redirect_uri)}"
        "&response_type=code"
        "&scope=snsapi_login"
        f"&state={state}"
        "#wechat_redirect"
    )


def _extract_wechat_qr_payload(html_text: str) -> dict[str, str]:
    """Extract QR uuid/image/poll endpoint from the WeChat qrconnect page."""
    import re
    from urllib.parse import urljoin

    text = html_text or ""
    qr_match = re.search(r"""src=["'](?P<src>[^"']*?/connect/qrcode/(?P<uuid>[^"'/<>\s?&#]+)[^"']*)["']""", text)
    if not qr_match:
        qr_match = re.search(r"""(?P<src>/connect/qrcode/(?P<uuid>[A-Za-z0-9_-]+))""", text)
    uuid = ""
    qr_image_url = ""
    if qr_match:
        src = qr_match.group("src")
        uuid = qr_match.group("uuid")
        qr_image_url = urljoin("https://open.weixin.qq.com", src)
    if not uuid:
        uuid_match = re.search(r"""uuid[=:]["']?(?P<uuid>[A-Za-z0-9_-]{8,})""", text)
        if uuid_match:
            uuid = uuid_match.group("uuid")
            qr_image_url = f"https://open.weixin.qq.com/connect/qrcode/{uuid}"

    poll_base = "https://lp.open.weixin.qq.com/connect/l/qrconnect"
    poll_match = re.search(r"""https://(?:lp|long)\.open\.weixin\.qq\.com/connect/l/qrconnect""", text)
    if poll_match:
        poll_base = poll_match.group(0)

    return {
        "uuid": uuid,
        "qr_image_url": qr_image_url,
        "poll_base": poll_base,
    }


async def _scrape_wechat_qr(oauth_url: str) -> dict[str, str]:
    import httpx

    async with httpx.AsyncClient(
        timeout=10.0,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    ) as client:
        resp = await client.get(oauth_url)
    payload = _extract_wechat_qr_payload(resp.text)
    if not payload.get("uuid"):
        raise RuntimeError("未能从微信授权页解析二维码 uuid")
    return payload


async def _complete_wechat_oauth_code(code: str, state: str) -> dict[str, Any]:
    import httpx

    from app.channels.config_store import save

    app_id = _wechat_app_id()
    app_secret = _wechat_app_secret()
    if not app_id or not app_secret:
        raise RuntimeError("缺少 AppID/AppSecret")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.weixin.qq.com/sns/oauth2/access_token",
            params={
                "appid": app_id,
                "secret": app_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
    try:
        token_data = resp.json()
    except Exception:
        token_data = {"raw": resp.text}
    if int(token_data.get("errcode", 0) or 0) != 0:
        raise RuntimeError(f"errcode={token_data.get('errcode')} errmsg={token_data.get('errmsg')}")

    openid = str(token_data.get("openid", ""))
    unionid = str(token_data.get("unionid", ""))
    refresh_token = str(token_data.get("refresh_token", ""))
    scope = str(token_data.get("scope", ""))
    if not openid:
        raise RuntimeError("微信返回空 openid")

    save(
        "wechat",
        {
            "oauth_authorized": "true",
            "oauth_openid": openid,
            "oauth_unionid": unionid,
            "oauth_scope": scope,
            "oauth_refresh_token": refresh_token,
        },
        enabled=True,
        connected=True,
    )
    result = {
        "authorized": True,
        "openid": openid,
        "unionid": unionid,
        "scope": scope,
    }
    _wechat_oauth_results[state] = result
    _wechat_oauth_states.pop(state, None)
    _wechat_oauth_sessions.pop(state, None)
    return result


async def _poll_wechat_qr_status(state: str, session: dict[str, Any]) -> dict[str, Any]:
    import re
    import time

    import httpx

    uuid = str(session.get("uuid") or "")
    if not uuid:
        return {"authorized": False, "expired": False}
    params: dict[str, Any] = {"uuid": uuid, "_": int(time.time() * 1000)}
    last = str(session.get("last_errcode") or "")
    if last:
        params["last"] = last
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(str(session.get("poll_base") or "https://lp.open.weixin.qq.com/connect/l/qrconnect"), params=params)
    except Exception as exc:
        return {"authorized": False, "expired": False, "poll_error": str(exc)}

    text = resp.text or ""
    err_match = re.search(r"window\.wx_errcode=(\d+)", text)
    code_match = re.search(r"window\.wx_code='([^']*)'", text)
    errcode = err_match.group(1) if err_match else ""
    wx_code = code_match.group(1) if code_match else ""
    if errcode:
        session["last_errcode"] = errcode
    if errcode == "405" and wx_code:
        return await _complete_wechat_oauth_code(wx_code, state)
    if errcode == "404":
        return {"authorized": False, "scanned": True, "expired": False}
    if errcode == "403":
        return {"authorized": False, "scanned": False, "canceled": True, "expired": False}
    if errcode in {"402", "500"}:
        _wechat_oauth_states.pop(state, None)
        _wechat_oauth_sessions.pop(state, None)
        return {"authorized": False, "expired": True}
    return {"authorized": False, "expired": False}


@router.post("/channels/wechat/oauth/initiate")
async def wechat_oauth_initiate(request: Request):
    """发起微信开放平台网站应用 OAuth，返回扫码授权 URL。"""
    import time

    app_id = _wechat_app_id()
    if not app_id:
        return {"success": False, "error": "请先配置微信开放平台 AppID"}

    state = secrets.token_urlsafe(32)
    _wechat_oauth_states[state] = time.time() + 600
    _wechat_oauth_results.pop(state, None)
    _wechat_oauth_sessions.pop(state, None)

    url = _build_wechat_oauth_url(request, state)
    data: dict[str, Any] = {"url": url, "state": state, "expires_in": 600}
    try:
        qr = await _scrape_wechat_qr(url)
        uuid = qr["uuid"]
        _wechat_oauth_sessions[state] = {
            "uuid": uuid,
            "poll_base": qr.get("poll_base") or "https://lp.open.weixin.qq.com/connect/l/qrconnect",
        }
        data.update({
            "uuid": uuid,
            "qr_image_url": qr.get("qr_image_url") or f"https://open.weixin.qq.com/connect/qrcode/{uuid}",
            "qr_proxy_url": f"{str(request.base_url).rstrip('/')}/api/kellai/channels/wechat/oauth/qrcode?uuid={uuid}",
            "poll_supported": True,
        })
    except Exception as exc:
        data["scrape_error"] = str(exc)
        data["poll_supported"] = False
    return {"success": True, "data": data}


@router.get("/channels/wechat/oauth/qrcode")
async def wechat_oauth_qrcode(uuid: str = ""):
    """Proxy the WeChat QR image so the desktop app can render it without iframe embedding."""
    import re

    import httpx

    clean_uuid = str(uuid or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", clean_uuid):
        raise HTTPException(status_code=400, detail={"message": "无效的二维码 uuid"})
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"https://open.weixin.qq.com/connect/qrcode/{clean_uuid}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"message": f"微信二维码拉取失败: HTTP {resp.status_code}"})
    content_type = resp.headers.get("content-type") or "image/jpeg"
    return Response(content=resp.content, media_type=content_type)


@router.get("/channels/wechat/oauth/callback")
async def wechat_oauth_callback(code: str = "", state: str = ""):
    """微信开放平台 OAuth 回调：用 code 换取 openid/unionid 并保存。"""
    import html
    import time

    from fastapi.responses import HTMLResponse

    if not state or state not in _wechat_oauth_states:
        if state in _wechat_oauth_results and _wechat_oauth_results[state].get("authorized"):
            return HTMLResponse(
                "<html><body>"
                "<h3>微信授权成功，请返回客来来应用</h3>"
                "<script>window.close();</script>"
                "</body></html>"
            )
        _wechat_oauth_results[state] = {"authorized": False, "expired": True, "error": "无效的 state 参数"}
        return HTMLResponse("<html><body><h3>授权失败：无效的 state 参数</h3></body></html>", status_code=400)

    expire_at = _wechat_oauth_states.pop(state)
    if time.time() > expire_at:
        _wechat_oauth_results[state] = {"authorized": False, "expired": True, "error": "state 已过期"}
        return HTMLResponse("<html><body><h3>授权失败：state 已过期，请重新发起授权</h3></body></html>", status_code=400)

    if not code:
        _wechat_oauth_results[state] = {"authorized": False, "error": "未收到授权码"}
        return HTMLResponse("<html><body><h3>授权失败：未收到授权码</h3></body></html>", status_code=400)

    try:
        await _complete_wechat_oauth_code(code, state)
    except Exception as exc:
        error = str(exc)
        _wechat_oauth_results[state] = {"authorized": False, "error": error}
        logger.warning("微信 OAuth 回调失败: %s", exc)
        return HTMLResponse(f"<html><body><h3>授权失败：{html.escape(error)}</h3></body></html>", status_code=400)
    return HTMLResponse(
        "<html><body>"
        "<h3>微信授权成功，请返回客来来应用</h3>"
        "<script>window.close();</script>"
        "</body></html>"
    )


@router.get("/channels/wechat/oauth/status")
async def wechat_oauth_status(state: str = ""):
    """查询微信开放平台 OAuth 授权状态（前端轮询）。"""
    import time

    if not state:
        return {"success": True, "data": {"authorized": False, "expired": True}}
    if state in _wechat_oauth_results:
        return {"success": True, "data": _wechat_oauth_results[state]}
    expire_at = _wechat_oauth_states.get(state)
    if not expire_at:
        return {"success": True, "data": {"authorized": False, "expired": True}}
    if time.time() > expire_at:
        _wechat_oauth_states.pop(state, None)
        _wechat_oauth_sessions.pop(state, None)
        return {"success": True, "data": {"authorized": False, "expired": True}}
    session = _wechat_oauth_sessions.get(state)
    if session:
        return {"success": True, "data": await _poll_wechat_qr_status(state, session)}
    return {"success": True, "data": {"authorized": False, "expired": False}}


# ---------------------------------------------------------------------------
# 企微 OAuth 端点
# ---------------------------------------------------------------------------

_wework_oauth_states: dict[str, float] = {}
_wework_oauth_results: dict[str, dict[str, Any]] = {}
_wework_oauth_return_urls: dict[str, str] = {}
_WEWORK_LOGIN_SCRIPT_URL = "https://wwcdn.weixin.qq.com/node/wework/wwopen/js/wwLogin-1.2.7.js"


def _wework_cfg(field: str) -> str:
    from app.channels.config_store import get_field

    return (
        get_field("wework", field)
        or os.environ.get(f"KELLAI_WECOM_{field.upper()}", "")
        or os.environ.get(f"KELLAI_WEWORK_{field.upper()}", "")
        or ""
    ).strip()


def _wework_corp_id() -> str:
    return _wework_cfg("corp_id") or _wework_cfg("corpid") or os.environ.get("WW_CORP_ID", "").strip()


def _wework_agent_id() -> str:
    return _wework_cfg("agent_id") or _wework_cfg("agentid") or os.environ.get("WW_AGENT_ID", "").strip()


def _wework_corp_secret() -> str:
    return (
        _wework_cfg("secret")
        or _wework_cfg("corp_secret")
        or _wework_cfg("corpsecret")
        or os.environ.get("WW_CORP_SECRET", "").strip()
    )


def _wework_customer_service_url() -> str:
    from urllib.parse import urlparse

    raw = (_wework_cfg("kf_url") or "").strip()
    open_kfid = (_wework_cfg("open_kfid") or "").strip()
    if raw:
        parsed = urlparse(raw)
        if parsed.scheme == "https" and parsed.netloc == "work.weixin.qq.com" and parsed.path.startswith("/kfid/"):
            return raw
    if open_kfid.startswith("kfc"):
        return f"https://work.weixin.qq.com/kfid/{open_kfid}"
    return ""


def _wework_redirect_uri(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/kellai/channels/wework/oauth/callback"


def _build_wework_oauth_url(request: Request, state: str) -> str:
    from urllib.parse import quote_plus

    encoded_redirect = quote_plus(_wework_redirect_uri(request))
    return (
        "https://open.work.weixin.qq.com/wwopen/sso/qrConnect"
        f"?appid={_wework_corp_id()}&agentid={_wework_agent_id()}"
        f"&redirect_uri={encoded_redirect}&state={state}"
    )


def _build_wework_login_payload(request: Request, state: str) -> dict[str, Any]:
    from urllib.parse import quote_plus

    return {
        "script_url": _WEWORK_LOGIN_SCRIPT_URL,
        "ww_login": {
            "appid": _wework_corp_id(),
            "agentid": _wework_agent_id(),
            "redirect_uri": quote_plus(_wework_redirect_uri(request)),
            "state": state,
            "href": "",
            "lang": "zh_CN",
            "business_type": "sso",
        },
    }


async def _complete_wework_oauth_code(code: str, state: str) -> dict[str, Any]:
    import httpx

    from app.channels.config_store import save

    corp_id = _wework_corp_id()
    corp_secret = _wework_corp_secret()
    if not corp_id or not corp_secret:
        raise RuntimeError("缺少 Corp ID/Secret")

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": corp_id, "corpsecret": corp_secret},
        )
        token_data = token_resp.json()
        if int(token_data.get("errcode", 0) or 0) != 0:
            raise RuntimeError(f"gettoken errcode={token_data.get('errcode')} errmsg={token_data.get('errmsg')}")
        access_token = str(token_data.get("access_token", ""))
        if not access_token:
            raise RuntimeError("企微 gettoken 返回空 access_token")

        user_resp = await client.get(
            "https://qyapi.weixin.qq.com/cgi-bin/auth/getuserinfo",
            params={"access_token": access_token, "code": code},
        )
        user_info = user_resp.json()
    if int(user_info.get("errcode", 0) or 0) != 0:
        raise RuntimeError(f"getuserinfo errcode={user_info.get('errcode')} errmsg={user_info.get('errmsg')}")

    user_id = str(user_info.get("userid") or user_info.get("UserId") or "")
    open_id = str(user_info.get("openid") or user_info.get("OpenId") or "")
    user_ticket = str(user_info.get("user_ticket") or "")
    identity = user_id or open_id
    if not identity:
        raise RuntimeError("企微未返回 userid/openid")

    save(
        "wework",
        {
            "oauth_authorized": "true",
            "oauth_user_id": user_id,
            "oauth_open_id": open_id,
            "oauth_user_ticket": user_ticket,
        },
        enabled=True,
        connected=True,
    )
    result = {
        "authorized": True,
        "user_id": user_id,
        "open_id": open_id,
    }
    _wework_oauth_results[state] = result
    _wework_oauth_states.pop(state, None)
    return result


def _wework_frontend_return_url(state: str) -> str:
    return _wework_oauth_return_urls.pop(state, "")


def _remember_wework_frontend_return_url(request: Request, state: str) -> None:
    from urllib.parse import urlparse

    raw = (request.headers.get("origin") or "").strip()
    if not raw:
        referer = (request.headers.get("referer") or "").strip()
        if referer:
            parsed = urlparse(referer)
            if parsed.scheme and parsed.netloc:
                raw = f"{parsed.scheme}://{parsed.netloc}"
    if raw.startswith(("http://127.0.0.1", "http://localhost", "https://")):
        _wework_oauth_return_urls[state] = raw.rstrip("/") + "/settings?tab=channels"


def _wework_callback_html(title: str, status_code: int = 200, return_url: str = ""):
    import html
    import json

    from fastapi.responses import HTMLResponse

    escaped_title = html.escape(title)
    target = json.dumps(return_url)
    script = (
        "<script>"
        "const target = " + target + ";"
        "if (window.opener && !window.opener.closed) { window.close(); }"
        "else if (target) { setTimeout(() => window.location.replace(target), 600); }"
        "</script>"
    )
    return HTMLResponse(f"<html><body><h3>{escaped_title}</h3>{script}</body></html>", status_code=status_code)


@router.post("/channels/wework/oauth/initiate")
async def wework_oauth_initiate(request: Request):
    """发起企微 OAuth 授权，返回官方内嵌扫码组件参数。"""
    import time

    corp_id = _wework_corp_id()
    agent_id = _wework_agent_id()
    corp_secret = _wework_corp_secret()

    if not corp_id or not agent_id or not corp_secret:
        return {"success": False, "error": "请先配置企业微信 Corp ID、Agent ID 和 Secret"}

    state = secrets.token_urlsafe(32)
    _wework_oauth_states[state] = time.time() + 300
    _wework_oauth_results.pop(state, None)
    _remember_wework_frontend_return_url(request, state)

    data = {
        "url": _build_wework_oauth_url(request, state),
        "state": state,
        "expires_in": 300,
        "embed_type": "ww_login",
        **_build_wework_login_payload(request, state),
    }
    return {"success": True, "data": data}


@router.get("/channels/wework/oauth/callback")
async def wework_oauth_callback(request: Request, code: str = "", state: str = ""):
    """企微 OAuth 回调：用 code 换取用户信息并保存。"""
    import time

    if not state or state not in _wework_oauth_states:
        if state in _wework_oauth_results and _wework_oauth_results[state].get("authorized"):
            return _wework_callback_html("企业微信授权成功，请返回客来来应用", return_url=_wework_frontend_return_url(state))
        return _wework_callback_html("授权失败：无效的 state 参数", status_code=400)

    expire_at = _wework_oauth_states.pop(state)
    if time.time() > expire_at:
        _wework_oauth_results[state] = {"authorized": False, "expired": True, "error": "state 已过期"}
        return _wework_callback_html("授权失败：state 已过期，请重新发起授权", status_code=400, return_url=_wework_frontend_return_url(state))

    if not code:
        _wework_oauth_results[state] = {"authorized": False, "error": "未收到授权码"}
        return _wework_callback_html("授权失败：未收到授权码", status_code=400, return_url=_wework_frontend_return_url(state))

    try:
        await _complete_wework_oauth_code(code, state)
    except Exception as exc:
        error = str(exc)
        _wework_oauth_results[state] = {"authorized": False, "error": error}
        logger.warning("企微 OAuth 回调失败: %s", exc)
        return _wework_callback_html(f"授权失败：{error}", status_code=400, return_url=_wework_frontend_return_url(state))

    return _wework_callback_html("企业微信授权成功，请返回客来来应用", return_url=_wework_frontend_return_url(state))


@router.get("/channels/wework/oauth/status")
async def wework_oauth_status(state: str = ""):
    """查询 OAuth 授权状态（前端轮询）。"""
    import time

    if not state:
        return {"success": True, "data": {"authorized": False, "expired": True}}

    if state in _wework_oauth_results:
        return {"success": True, "data": _wework_oauth_results[state]}

    expire_at = _wework_oauth_states.get(state)
    if not expire_at:
        return {"success": True, "data": {"authorized": False, "expired": True}}
    if time.time() > expire_at:
        _wework_oauth_states.pop(state, None)
        _wework_oauth_results[state] = {"authorized": False, "expired": True}
        return {"success": True, "data": {"authorized": False, "expired": True}}

    return {"success": True, "data": {"authorized": False}}


@router.api_route("/webhook/wework/suite", methods=["GET", "POST"])
async def wework_suite_callback(
    request: Request,
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
):
    """企业微信服务商指令回调：URL 校验、suite_ticket、授权变更/取消。"""
    from fastapi.responses import PlainTextResponse

    from app.services.wework_suite import (
        WeWorkSuiteError,
        decrypt_callback,
        handle_suite_event,
        parse_encrypted_xml,
        parse_plain_event,
        suite_config,
        verify_signature,
    )

    try:
        if request.method == "GET":
            verify_signature(msg_signature, timestamp, nonce, echostr)
            # 企业微信在后台校验指令回调 URL 时，AES 包尾部的 ReceiveId
            # 可能是服务商企业 CorpID，而不是第三方应用 SuiteID。签名和 AES
            # 已能证明请求来自持有同一 Token/EncodingAESKey 的平台；GET 校验只需
            # 原样返回解密后的 echostr，不能据此拒绝合法的服务商校验请求。
            return PlainTextResponse(decrypt_callback(echostr, validate_suite_id=False))

        raw_body = await request.body()
        encrypted = parse_encrypted_xml(raw_body)
        verify_signature(msg_signature, timestamp, nonce, encrypted)
        event = parse_plain_event(decrypt_callback(encrypted, validate_suite_id=False))
        configured_suite_id = suite_config()["suite_id"]
        if configured_suite_id and event.get("SuiteId") != configured_suite_id:
            raise WeWorkSuiteError("企业微信回调 SuiteID 不匹配")
        result = await handle_suite_event(event)
        logger.info("企业微信服务商指令回调完成: info_type=%s", result.get("info_type"))
        return PlainTextResponse("success")
    except WeWorkSuiteError as exc:
        logger.warning("企业微信服务商指令回调失败: %s", exc)
        return PlainTextResponse(str(exc), status_code=400)


class WeWorkAcquisitionLinkCreate(BaseModel):
    link_name: str = Field(min_length=1, max_length=30)
    userids: list[str] = Field(min_length=1, max_length=500)
    skip_verify: bool = True


@router.get("/channels/wework/suite/readiness")
async def wework_suite_readiness(current_user: CurrentUser):
    """返回服务商配置是否具备生成企业安装二维码的条件。"""
    from app.services.wework_suite import (
        WeWorkSuiteError,
        remote_bridge_enabled,
        remote_suite_readiness,
        suite_readiness,
    )

    _ = current_user
    try:
        data = await remote_suite_readiness() if remote_bridge_enabled() else suite_readiness()
    except WeWorkSuiteError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.post("/channels/wework/install")
async def wework_install(current_user: CurrentUser):
    """为当前客来来团队生成第三方应用安装 URL，作为企业微信主绑定入口。"""
    from app.services.wework_suite import (
        WeWorkSuiteError,
        create_install_url,
        remote_bridge_enabled,
        remote_create_install_url,
    )

    try:
        args = {
            "team_id": int(current_user.get("team_id") or 0),
            "user_id": int(current_user.get("id") or 0),
        }
        data = (
            await remote_create_install_url(**args)
            if remote_bridge_enabled()
            else await create_install_url(**args)
        )
    except WeWorkSuiteError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.get("/channels/wework/install/callback")
async def wework_install_callback(state: str = "", auth_code: str = ""):
    """企业管理员确认安装后的公网回调。"""
    import html

    from fastapi.responses import HTMLResponse

    from app.services.wework_suite import WeWorkSuiteError, complete_install

    if not state or not auth_code:
        return HTMLResponse("<h3>企业微信授权失败：缺少 state/auth_code</h3>", status_code=400)
    try:
        result = await complete_install(state=state, auth_code=auth_code)
    except WeWorkSuiteError as exc:
        logger.warning("企业微信第三方应用安装回调失败: %s", exc)
        return HTMLResponse(f"<h3>企业微信授权失败：{html.escape(str(exc))}</h3>", status_code=400)
    corp_name = html.escape(str(result.get("corp_name") or result.get("auth_corpid") or "企业"))
    return HTMLResponse(
        "<html><body>"
        f"<h3>{corp_name} 已成功绑定客来来</h3>"
        "<p>可以关闭此页面并返回客来来，客户列表将自动同步。</p>"
        "<script>setTimeout(() => window.close(), 1200);</script>"
        "</body></html>"
    )


@router.get("/channels/wework/install/status")
async def wework_install_status(state: str, current_user: CurrentUser):
    """桌面端轮询当前团队的第三方应用安装状态。"""
    from app.services.wework_suite import (
        WeWorkSuiteError,
        get_install_status,
        remote_bridge_enabled,
        remote_get_install_status,
    )

    team_id = int(current_user.get("team_id") or 0)
    try:
        data = (
            await remote_get_install_status(state=state, team_id=team_id)
            if remote_bridge_enabled()
            else get_install_status(state=state, team_id=team_id)
        )
    except WeWorkSuiteError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.post("/channels/wework/customers/sync")
async def wework_customers_sync(current_user: CurrentUser, limit: int = 500):
    """使用当前团队的永久授权同步外部联系人，并写入客来来真实客户列表。"""
    from app.services.wework_suite import (
        WeWorkSuiteError,
        remote_bridge_enabled,
        remote_sync_external_customers,
        sync_external_customers,
    )

    try:
        team_id = int(current_user.get("team_id") or 0)
        clean_limit = max(1, min(int(limit), 1000))
        data = (
            await remote_sync_external_customers(team_id, limit=clean_limit)
            if remote_bridge_enabled()
            else await sync_external_customers(team_id, limit=clean_limit)
        )
    except WeWorkSuiteError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.get("/channels/wework/customers")
async def wework_customers(current_user: CurrentUser, limit: int = 500):
    """读取当前团队已经同步的企业微信外部联系人。"""
    from app.services.wework_suite import (
        WeWorkSuiteError,
        list_customers,
        remote_bridge_enabled,
        remote_list_customers,
    )

    team_id = int(current_user.get("team_id") or 0)
    clean_limit = max(1, min(int(limit), 1000))
    try:
        customers = (
            await remote_list_customers(team_id, limit=clean_limit)
            if remote_bridge_enabled()
            else list_customers(team_id, limit=clean_limit)
        )
    except WeWorkSuiteError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": {"customers": customers, "total": len(customers)}}


@router.get("/channels/wework/acquisition/members")
async def wework_acquisition_members(current_user: CurrentUser):
    """列出当前登录团队可用于获客链接的企业微信跟进成员。"""
    from app.services.wework_suite import (
        WeWorkSuiteError,
        list_acquisition_members,
        remote_bridge_enabled,
        remote_list_acquisition_members,
    )

    team_id = int(current_user.get("team_id") or 0)
    if team_id <= 0:
        return {"success": False, "error": "当前账号没有有效团队"}
    try:
        data = (
            await remote_list_acquisition_members(team_id)
            if remote_bridge_enabled()
            else await list_acquisition_members(team_id)
        )
    except WeWorkSuiteError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


@router.post("/channels/wework/acquisition/links")
async def wework_acquisition_link_create(
    payload: WeWorkAcquisitionLinkCreate,
    current_user: CurrentUser,
):
    """只使用当前登录团队的企业微信授权创建获客链接。"""
    from app.services.wework_suite import (
        WeWorkSuiteError,
        create_acquisition_link,
        remote_bridge_enabled,
        remote_create_acquisition_link,
    )

    team_id = int(current_user.get("team_id") or 0)
    if team_id <= 0:
        return {"success": False, "error": "当前账号没有有效团队"}
    args = {
        "team_id": team_id,
        "link_name": payload.link_name,
        "userids": payload.userids,
        "skip_verify": payload.skip_verify,
    }
    try:
        data = (
            await remote_create_acquisition_link(**args)
            if remote_bridge_enabled()
            else await create_acquisition_link(**args)
        )
    except WeWorkSuiteError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": data}


def _verify_wework_bridge(request: Request) -> None:
    from app.services.wework_suite import WeWorkSuiteError, verify_bridge_key

    try:
        verify_bridge_key(request.headers.get("X-Kellai-WeWork-Bridge-Key", ""))
    except WeWorkSuiteError as exc:
        raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc


@router.get("/internal/wework/readiness")
async def internal_wework_readiness(request: Request):
    from app.services.wework_suite import suite_readiness

    _verify_wework_bridge(request)
    return {"success": True, "data": suite_readiness()}


@router.post("/internal/wework/install")
async def internal_wework_install(request: Request, team_id: int, user_id: int):
    from app.services.wework_suite import WeWorkSuiteError, create_install_url

    try:
        _verify_wework_bridge(request)
        data = await create_install_url(team_id=team_id, user_id=user_id)
        return {"success": True, "data": data}
    except WeWorkSuiteError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.get("/internal/wework/install/status")
async def internal_wework_install_status(request: Request, state: str, team_id: int):
    from app.services.wework_suite import WeWorkSuiteError, get_install_status

    try:
        _verify_wework_bridge(request)
        data = get_install_status(state=state, team_id=team_id)
        return {"success": True, "data": data}
    except WeWorkSuiteError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.post("/internal/wework/customers/sync")
async def internal_wework_customers_sync(request: Request, team_id: int, limit: int = 500):
    from app.services.wework_suite import WeWorkSuiteError, sync_external_customers

    try:
        _verify_wework_bridge(request)
        data = await sync_external_customers(team_id, limit=max(1, min(int(limit), 1000)))
        return {"success": True, "data": data}
    except WeWorkSuiteError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.get("/internal/wework/customers")
async def internal_wework_customers(request: Request, team_id: int, limit: int = 500):
    from app.services.wework_suite import WeWorkSuiteError, list_customers

    try:
        _verify_wework_bridge(request)
        customers = list_customers(team_id, limit=max(1, min(int(limit), 1000)))
        return {"success": True, "data": {"customers": customers, "total": len(customers)}}
    except WeWorkSuiteError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.get("/internal/wework/acquisition/members")
async def internal_wework_acquisition_members(request: Request, team_id: int):
    from app.services.wework_suite import WeWorkSuiteError, list_acquisition_members

    try:
        _verify_wework_bridge(request)
        if int(team_id) <= 0:
            raise WeWorkSuiteError("当前账号没有有效团队")
        data = await list_acquisition_members(int(team_id))
        return {"success": True, "data": data}
    except WeWorkSuiteError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.post("/internal/wework/acquisition/links")
async def internal_wework_acquisition_link_create(
    request: Request,
    payload: WeWorkAcquisitionLinkCreate,
    team_id: int,
):
    from app.services.wework_suite import WeWorkSuiteError, create_acquisition_link

    try:
        _verify_wework_bridge(request)
        if int(team_id) <= 0:
            raise WeWorkSuiteError("当前账号没有有效团队")
        data = await create_acquisition_link(
            int(team_id),
            link_name=payload.link_name,
            userids=payload.userids,
            skip_verify=payload.skip_verify,
        )
        return {"success": True, "data": data}
    except WeWorkSuiteError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.get("/channels/wework/customer-entry")
def wework_customer_entry(request: Request, source: str = "settings", mode: str = ""):
    """公开客户入口：记录来源并跳转到已配置的企业微信客服链接。"""
    from urllib.parse import urlencode

    from fastapi.responses import RedirectResponse

    target_url = _wework_customer_service_url()
    if not target_url:
        if mode == "json":
            return {"success": False, "error": "请先配置企业微信客服接待链接或 open_kfid"}
        raise HTTPException(status_code=404, detail={"message": "企业微信客服入口未配置"})

    clean_source = "".join(ch for ch in (source or "settings") if ch.isalnum() or ch in "-_:.")[:80] or "settings"
    logger.info(
        "企业微信客服入口访问: source=%s ip=%s target=open_kfid",
        clean_source,
        getattr(request.client, "host", "-") if request.client else "-",
    )
    entry_url = (
        f"{str(request.base_url).rstrip('/')}/api/kellai/channels/wework/customer-entry?"
        f"{urlencode({'source': clean_source})}"
    )
    if mode == "json":
        return {
            "success": True,
            "data": {
                "entry_url": entry_url,
                "target_url": target_url,
                "source": clean_source,
            },
        }
    return RedirectResponse(target_url, status_code=307)


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
        if team_id:
            team_customer_ids = {
                c["customer_id"]
                for c in all_clients
                if int(c.get("team_id") or 0) == int(team_id)
            }
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
async def send_message(body: ChannelSendMessageBody, request: Request = None):
    """统一发送消息。"""
    import uuid
    from datetime import datetime, timezone

    from app.channels import ChannelRegistry
    from app.channels.base import UnifiedMessage
    from app.services.message_store import get_messages, save_message

    reg = ChannelRegistry()
    try:
        adapter = reg.get(body.channel_type)
    except KeyError:
        return {"success": False, "error": f"未注册的渠道类型: {body.channel_type}"}
    user = get_request_user(request) if request is not None else None
    team_id = int((user or {}).get("team_id") or 0)
    logger.info(
        "渠道发送开始: team_id=%s customer_id=%s channel=%s contact_id=%s",
        team_id,
        body.customer_id,
        body.channel_type,
        body.contact_id,
    )
    contact_name = ""
    try:
        for stored_message in get_messages(
            body.customer_id,
            body.channel_type,
            limit=100,
        ):
            if str(stored_message.contact_id or "") != str(body.contact_id or ""):
                continue
            contact_name = str(stored_message.contact_name or "").strip()
            if contact_name:
                break
    except Exception:
        logger.debug(
            "发送前解析联系人名称失败: customer_id=%s channel=%s",
            body.customer_id,
            body.channel_type,
            exc_info=True,
        )
    if body.desktop_result is not None:
        client_host = str(getattr(getattr(request, "client", None), "host", "") or "")
        desktop_header = str(request.headers.get("X-Kellai-Desktop-Delivery", ""))
        supplied = dict(body.desktop_result)
        valid_desktop_receipt = (
            body.channel_type == "douyin"
            and client_host in {"127.0.0.1", "::1", "localhost"}
            and desktop_header == "1"
            and supplied.get("success") is True
            and supplied.get("message_sent") is True
            and supplied.get("source") == "douyin_desktop_automation"
            and str(supplied.get("contact_id") or "") == str(body.contact_id)
        )
        if not valid_desktop_receipt:
            logger.warning(
                "拒绝无效桌面发送回执: client=%s channel=%s customer_id=%s",
                client_host,
                body.channel_type,
                body.customer_id,
            )
            return {"success": False, "error": "无效的客来来桌面发送回执"}
        result = {
            "success": True,
            "message_id": str(supplied.get("message_id") or ""),
            "error": "",
            "source": "douyin_desktop_automation",
            "message_sent": True,
            "contact_name": str(supplied.get("contact_name") or contact_name),
            "contact_id": str(body.contact_id),
            "reused_conversation": bool(supplied.get("reused_conversation")),
            "pending_portal_sync": bool(supplied.get("pending_portal_sync", True)),
        }
    else:
        result = await adapter.send_message(
            body.contact_id,
            body.content,
            team_id=team_id,
            customer_id=body.customer_id,
            contact_name=contact_name,
        )
    if not result.get("success", False):
        logger.warning(
            "渠道发送失败: team_id=%s customer_id=%s channel=%s error=%s",
            team_id,
            body.customer_id,
            body.channel_type,
            result.get("error") or result.get("message") or "未知错误",
        )
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
        contact_name=contact_name,
        direction="outbound",
        content=body.content,
        content_type="text",
        metadata={
            **result,
            "team_id": team_id,
            "agent_user_id": int((user or {}).get("id") or 0),
            "auto_reply_inbound_id": str(body.auto_reply_inbound_id or ""),
        },
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
    if body.auto_reply_inbound_id:
        try:
            from app.services.auto_reply_runtime import complete_job

            complete_job(
                body.auto_reply_inbound_id,
                success=True,
                outbound_message_id=(
                    msg.id if persisted else str(result.get("message_id") or "")
                ),
                team_id=team_id,
            )
        except Exception:
            logger.warning(
                "自动回复已发送但任务完成状态更新失败: inbound_message_id=%s",
                body.auto_reply_inbound_id,
                exc_info=True,
            )
    logger.info(
        "渠道发送完成: team_id=%s customer_id=%s channel=%s source=%s persisted=%s",
        team_id,
        body.customer_id,
        body.channel_type,
        result.get("source") or "api",
        persisted,
    )
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
    visible_ids = {
        int(c["customer_id"])
        for c in all_clients
        if c.get("customer_id")
        and (
            not team_id
            or int(c.get("team_id") or 0) == int(team_id)
        )
    }

    summary = _summary()
    if visible_ids:
        filtered_by = {
            cid: cnt
            for cid, cnt in summary["by_customer"].items()
            if int(cid) in visible_ids
        }
        filtered_total = sum(filtered_by.values())
    else:
        filtered_by = {}
        filtered_total = 0

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
        visible_ids = {
            int(c["customer_id"])
            for c in list_pipeline_client_summaries()
            if c.get("customer_id")
            and int(c.get("team_id") or 0) == int(team_id)
        }

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
                f"SELECT id, customer_id FROM kellai_messages WHERE team_id = ? "
                f"AND id IN ({placeholders})",
                [int(team_id or 0), *body.message_ids],
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


# ---------------------------------------------------------------------------
# 统一接待：在线状态、抢单锁、管理分配与负载均衡
# ---------------------------------------------------------------------------


def _workforce_team_id(current_user: dict) -> int:
    team_id = int(current_user.get("team_id") or 0)
    if team_id <= 0:
        raise HTTPException(status_code=400, detail={"message": "当前账号尚未加入团队"})
    return team_id


def _ensure_customer_in_team(customer_id: int, team_id: int) -> None:
    from app.services.pipeline import load_pipeline
    from app.services.tenant_context import tenant_scope

    with tenant_scope(int(team_id)):
        doc = load_pipeline(int(customer_id))
    doc_team_id = int(doc.get("team_id") or 0)
    if doc_team_id != int(team_id):
        raise HTTPException(status_code=404, detail={"message": "客户不在当前团队中"})


@router.post("/workforce/presence/heartbeat")
def workforce_presence_heartbeat(
    body: WorkforceHeartbeatBody,
    current_user: CurrentUser,
):
    from app.services.workforce_routing import heartbeat

    team_id = _workforce_team_id(current_user)
    data = heartbeat(
        team_id=team_id,
        user_id=int(current_user.get("id") or 0),
        state=body.state,
    )
    return {"success": True, "data": data}


@router.get("/workforce/overview")
def workforce_overview(current_user: CurrentUser):
    from app.services.workforce_routing import routing_overview

    team_id = _workforce_team_id(current_user)
    return {"success": True, "data": routing_overview(team_id)}


@router.get("/workforce/customers/{customer_id}/assignment")
def workforce_customer_assignment(customer_id: int, current_user: CurrentUser):
    from app.services.workforce_routing import assignment_for_customer

    team_id = _workforce_team_id(current_user)
    _ensure_customer_in_team(customer_id, team_id)
    assignment = assignment_for_customer(customer_id)
    if assignment and int(assignment.get("team_id") or 0) != team_id:
        assignment = None
    return {"success": True, "data": {"assignment": assignment}}


@router.post("/workforce/customers/{customer_id}/claim")
def workforce_claim_customer(customer_id: int, current_user: CurrentUser):
    from app.services.workforce_routing import AssignmentConflict, claim_customer

    team_id = _workforce_team_id(current_user)
    _ensure_customer_in_team(customer_id, team_id)
    try:
        assignment = claim_customer(
            customer_id=customer_id,
            team_id=team_id,
            user_id=int(current_user.get("id") or 0),
        )
    except AssignmentConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "assignment": exc.assignment},
        ) from exc
    return {"success": True, "data": {"assignment": assignment}}


@router.post("/workforce/customers/{customer_id}/assign")
def workforce_assign_customer(
    customer_id: int,
    body: WorkforceAssignBody,
    current_user: CurrentUser,
):
    from app.services.workforce_routing import assign_customer

    if str(current_user.get("role") or "") not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail={"message": "仅管理者可重新分配客户"})
    team_id = _workforce_team_id(current_user)
    _ensure_customer_in_team(customer_id, team_id)
    try:
        assignment = assign_customer(
            customer_id=customer_id,
            team_id=team_id,
            assignee_user_id=body.assignee_user_id,
            actor_user_id=int(current_user.get("id") or 0),
            source="manager",
            allow_override=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    return {"success": True, "data": {"assignment": assignment}}


@router.post("/workforce/customers/{customer_id}/auto-assign")
def workforce_auto_assign_customer(customer_id: int, current_user: CurrentUser):
    from app.services.workforce_routing import auto_assign_customer

    if str(current_user.get("role") or "") not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail={"message": "仅管理者可触发自动分配"})
    team_id = _workforce_team_id(current_user)
    _ensure_customer_in_team(customer_id, team_id)
    assignment = auto_assign_customer(
        customer_id=customer_id,
        team_id=team_id,
        source="manager_auto_route",
    )
    if assignment is None:
        return {"success": False, "error": "当前团队没有可接待成员"}
    return {"success": True, "data": {"assignment": assignment}}


@router.post("/workforce/customers/{customer_id}/release")
def workforce_release_customer(customer_id: int, current_user: CurrentUser):
    from app.services.workforce_routing import assignment_for_customer, release_customer

    team_id = _workforce_team_id(current_user)
    _ensure_customer_in_team(customer_id, team_id)
    assignment = assignment_for_customer(customer_id)
    is_manager = str(current_user.get("role") or "") in {"owner", "admin"}
    is_assignee = bool(
        assignment
        and int(assignment.get("assignee_user_id") or 0) == int(current_user.get("id") or 0)
    )
    if not (is_manager or is_assignee):
        raise HTTPException(status_code=403, detail={"message": "仅负责人或管理者可释放客户"})
    released = release_customer(
        customer_id=customer_id,
        team_id=team_id,
        actor_user_id=int(current_user.get("id") or 0),
    )
    return {"success": True, "data": {"assignment": released}}


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
    team_id = int(current_user.get("team_id") or 0)
    if team_id:
        clients = [c for c in clients if int(c.get("team_id") or 0) == team_id]

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
            "version": "1.0.1",
            "independent": True,
        },
    }


def _require_xcmax_loopback(request: Request) -> str:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="XCMAX 数据访问仅允许本机桌面端")
    authorization = request.headers.get("Authorization", "")
    return authorization[7:].strip() if authorization.startswith("Bearer ") else ""


def _require_xcmax_desktop_handoff(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="XCMAX 桌面登录仅允许本机访问")
    if request.headers.get("X-Kellai-Local-Pairing") != "1":
        raise HTTPException(status_code=403, detail="缺少本机绑定校验")


@router.post("/auth/xcmax-desktop")
def auth_xcmax_desktop(request: Request):
    """Enter 客来来 for an active local XCMAX authorization handoff."""
    _require_xcmax_desktop_handoff(request)
    from app.services.xcmax_integration import create_desktop_login_for_pending_pairing

    try:
        return create_desktop_login_for_pending_pairing()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/integrations/xcmax/status")
def xcmax_integration_status(current_user: CurrentUser):
    from app.services.xcmax_integration import public_status

    _ = current_user
    return {"success": True, "data": public_status()}


@router.get("/integrations/xcmax/pending")
def xcmax_integration_pending(current_user: CurrentUser):
    from app.services.xcmax_integration import pending_authorization

    _ = current_user
    try:
        pending = pending_authorization()
    except RuntimeError as exc:
        # XCMAX 未运行、版本较旧或没有绑定路由都属于“当前无待授权”，
        # 不应让客来来桌面端收到 500/Network Error。
        logger.debug("读取 XCMAX 待授权状态失败: %s", exc)
        pending = None
    return {"success": True, "data": pending}


@router.post("/integrations/xcmax/approve")
def xcmax_integration_approve(body: XcmaxAuthorizeBody, current_user: CurrentUser):
    from app.services.xcmax_integration import approve_authorization

    try:
        connection = approve_authorization(
            request_id=body.request_id,
            authorization_secret=body.authorization_secret,
            accepted_scopes=body.accepted_scopes,
            current_user=current_user,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": connection}


@router.post("/integrations/xcmax/cancel")
def xcmax_integration_cancel(body: XcmaxCancelBody, current_user: CurrentUser):
    from app.services.xcmax_integration import cancel_authorization

    _ = current_user
    try:
        cancel_authorization(
            request_id=body.request_id,
            authorization_secret=body.authorization_secret,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True}


@router.post("/integrations/xcmax/disconnect")
def xcmax_integration_disconnect(current_user: CurrentUser):
    from app.services.xcmax_integration import disconnect

    _ = current_user
    disconnect()
    return {"success": True}


@router.get("/integrations/xcmax/data-status")
def xcmax_data_status(request: Request):
    from app.services.message_store import get_unread_summary
    from app.services.pipeline import list_pipeline_client_summaries
    from app.services.xcmax_integration import authorize_access_token
    from app.services.tenant_context import tenant_scope

    connection = authorize_access_token(
        _require_xcmax_loopback(request), "customer_profiles.read"
    )
    with tenant_scope(int(connection.get("team_id") or 0)):
        customers = list_pipeline_client_summaries(include_demo=False)
        unread = get_unread_summary()
    return {
        "success": True,
        "data": {
            "customer_count": len(customers),
            "unread_message_count": int(unread.get("total") or 0),
            "latest_customer_at": str(customers[0].get("updated_at") or "") if customers else "",
        },
    }


@router.get("/integrations/xcmax/customers")
def xcmax_customers(request: Request, limit: int = 12):
    from app.services.pipeline import list_pipeline_client_summaries
    from app.services.xcmax_integration import authorize_access_token
    from app.services.tenant_context import tenant_scope

    connection = authorize_access_token(
        _require_xcmax_loopback(request), "customer_profiles.read"
    )
    with tenant_scope(int(connection.get("team_id") or 0)):
        rows = list_pipeline_client_summaries(include_demo=False)[
            : max(1, min(int(limit), 50))
        ]
    customers = [
        {
            "customer_id": int(row.get("customer_id") or 0),
            "display_name": str(row.get("display_name") or "未命名客户"),
            "stage": str(row.get("stage") or ""),
            "stage_label": str(row.get("stage_label") or ""),
            "channel_sources": list(row.get("channel_sources") or []),
            "last_message_preview": str(row.get("last_message_preview") or "")[:500],
            "updated_at": str(row.get("updated_at") or ""),
        }
        for row in rows
    ]
    return {"success": True, "data": {"customers": customers, "total": len(rows)}}


@router.get("/integrations/xcmax/customers/{customer_id}/conversations")
def xcmax_customer_conversations(customer_id: int, request: Request, limit: int = 30):
    from app.services.message_store import get_messages_with_state
    from app.services.xcmax_integration import authorize_access_token
    from app.services.tenant_context import tenant_scope

    connection = authorize_access_token(
        _require_xcmax_loopback(request), "customer_conversations.read"
    )
    with tenant_scope(int(connection.get("team_id") or 0)):
        messages = get_messages_with_state(
            int(customer_id), limit=max(1, min(int(limit), 100))
        )
    return {"success": True, "data": {"customer_id": int(customer_id), "messages": messages}}


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
    from app.services.ai_copilot import format_suggestion_payload, suggest_reply
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
        history = [
            f"{'客服' if m.direction == 'outbound' else '客户'}：{m.content}"
            for m in reversed(msgs)
        ]
    data = format_suggestion_payload(
        suggest_reply(
            uid,
            message=body.message,
            intent=body.intent,
            stage=stage,
            history=history,
        )
    )
    return {"success": True, "data": data}


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
        history = [
            f"{'客服' if m.direction == 'outbound' else '客户'}：{m.content}"
            for m in reversed(msgs)
        ]
    result = generate_auto_reply(
        uid,
        message=body.message,
        intent=body.intent,
        stage=stage,
        history=history,
    )
    return {"success": True, "data": result}


@router.post("/ai/auto-reply/jobs/claim")
def ai_auto_reply_claim(body: AutoReplyClaimBody, current_user: CurrentUser):
    """桌面端领取已去重、带租约的真实自动回复任务。"""
    from app.services.auto_reply_runtime import claim_jobs

    jobs = claim_jobs(
        team_id=int(current_user.get("team_id") or 0),
        limit=body.limit,
    )
    return {"success": True, "data": {"jobs": jobs}}


@router.post("/ai/auto-reply/jobs/result")
def ai_auto_reply_result(body: AutoReplyResultBody, current_user: CurrentUser):
    """记录桌面端自动回复发送结果；失败任务按退避策略重试。"""
    from app.services.auto_reply_runtime import complete_job

    updated = complete_job(
        body.inbound_message_id,
        success=body.success,
        error=body.error,
        outbound_message_id=body.outbound_message_id,
        team_id=int(current_user.get("team_id") or 0),
    )
    return {"success": True, "data": {"updated": updated}}


@router.get("/ai/auto-reply/runtime-status")
def ai_auto_reply_runtime_status(current_user: CurrentUser):
    """自动回复真实运行状态与最近一次处理结果。"""
    from app.services.auto_reply_runtime import runtime_status

    return {
        "success": True,
        "data": runtime_status(team_id=int(current_user.get("team_id") or 0)),
    }


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

_qr_login_sessions: dict[str, dict[str, Any]] = {}
_QR_LOGIN_TTL_SECONDS = 180


def _frontend_origin_from_request(request: Request) -> str:
    from urllib.parse import urlparse

    configured = (
        os.getenv("KELLAI_QR_LOGIN_FRONTEND_URL")
        or os.getenv("KELLAI_PUBLIC_FRONTEND_URL")
        or ""
    ).strip()
    if configured.startswith(("http://", "https://")):
        return configured.rstrip("/")

    # 扫码登录从登录页发起。优先从 Referer 保留部署子路径，例如
    # https://xiu-ci.com/kellai/login -> https://xiu-ci.com/kellai。
    referer = (request.headers.get("referer") or "").strip()
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            path = (parsed.path or "").rstrip("/")
            base_path = path[:-len("/login")] if path.endswith("/login") else ""
            if base_path:
                return f"{parsed.scheme}://{parsed.netloc}{base_path}"

    origin = (request.headers.get("origin") or "").strip()
    if not origin and referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin.startswith(("http://127.0.0.1", "http://localhost", "https://")):
        return origin.rstrip("/")
    return str(request.base_url).rstrip("/")


def _cleanup_qr_login_sessions(now: float) -> None:
    expired = [
        sid for sid, session in _qr_login_sessions.items()
        if float(session.get("expires_at") or 0) <= now
    ]
    for sid in expired:
        _qr_login_sessions.pop(sid, None)


@router.post("/auth/qr/start")
def auth_qr_start(request: Request):
    """桌面端发起扫码登录，返回二维码内容 URL 与轮询 session_id。"""
    import time
    from urllib.parse import urlencode

    now = time.time()
    _cleanup_qr_login_sessions(now)
    session_id = secrets.token_urlsafe(32)
    secret = secrets.token_urlsafe(24)
    expires_at = now + _QR_LOGIN_TTL_SECONDS
    _qr_login_sessions[session_id] = {
        "secret": secret,
        "status": "waiting",
        "expires_at": expires_at,
        "created_at": now,
        "scanned_at": 0.0,
        "authorized_at": 0.0,
        "user": None,
        "login": None,
        "error": "",
    }
    frontend_origin = _frontend_origin_from_request(request)
    login_url = f"{frontend_origin}/login?{urlencode({'qr_session': session_id, 'qr_secret': secret})}"
    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "secret": secret,
            "login_url": login_url,
            "expires_in": _QR_LOGIN_TTL_SECONDS,
            "expires_at": expires_at,
        },
    }


@router.get("/auth/qr/status")
def auth_qr_status(session_id: str = ""):
    """桌面端轮询扫码登录状态。authorized 时返回登录 token。"""
    import time

    now = time.time()
    _cleanup_qr_login_sessions(now)
    session = _qr_login_sessions.get((session_id or "").strip())
    if not session:
        return {"success": True, "data": {"status": "expired", "expired": True}}
    if float(session.get("expires_at") or 0) <= now:
        _qr_login_sessions.pop(session_id, None)
        return {"success": True, "data": {"status": "expired", "expired": True}}
    status = str(session.get("status") or "waiting")
    data: dict[str, Any] = {
        "status": status,
        "scanned": status in {"scanned", "authorized"},
        "authorized": status == "authorized",
        "expired": False,
        "expires_in": max(0, int(float(session.get("expires_at") or 0) - now)),
    }
    if status == "authorized":
        data["login"] = session.get("login")
        data["user"] = session.get("user")
    if status in {"canceled", "failed"}:
        data["error"] = str(session.get("error") or "")
    return {"success": True, "data": data}


@router.post("/auth/qr/scan")
def auth_qr_scan(body: QrLoginBody):
    """扫码设备打开二维码链接后标记已扫描。"""
    import time

    session = _qr_login_sessions.get(body.session_id)
    if not session or float(session.get("expires_at") or 0) <= time.time():
        return {"success": False, "error": "二维码已过期"}
    if secrets.compare_digest(str(session.get("secret") or ""), body.secret):
        if session.get("status") == "waiting":
            session["status"] = "scanned"
            session["scanned_at"] = time.time()
        return {"success": True, "data": {"status": session.get("status")}}
    return {"success": False, "error": "二维码无效"}


@router.post("/auth/qr/confirm")
def auth_qr_confirm(body: QrLoginBody, current_user: CurrentUser):
    """扫码设备确认登录，把当前账号授权给发起扫码的桌面会话。"""
    import time

    from app.services.auth import create_login_session_for_user

    session = _qr_login_sessions.get(body.session_id)
    if not session or float(session.get("expires_at") or 0) <= time.time():
        return {"success": False, "error": "二维码已过期"}
    if not secrets.compare_digest(str(session.get("secret") or ""), body.secret):
        return {"success": False, "error": "二维码无效"}
    if session.get("status") in {"authorized", "canceled"}:
        return {"success": False, "error": "该二维码已处理"}

    login = create_login_session_for_user(int(current_user.get("id") or 0))
    if not login.get("success"):
        session["status"] = "failed"
        session["error"] = str(login.get("error") or "授权失败")
        return login
    session["status"] = "authorized"
    session["authorized_at"] = time.time()
    session["user"] = login.get("user")
    session["login"] = login
    return {"success": True, "data": {"status": "authorized", "user": login.get("user")}}


@router.post("/auth/qr/cancel")
def auth_qr_cancel(body: QrLoginBody):
    """扫码设备取消本次登录。"""
    session = _qr_login_sessions.get(body.session_id)
    if not session:
        return {"success": True, "data": {"status": "expired"}}
    if secrets.compare_digest(str(session.get("secret") or ""), body.secret):
        session["status"] = "canceled"
        session["error"] = "用户已取消"
        return {"success": True, "data": {"status": "canceled"}}
    return {"success": False, "error": "二维码无效"}


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
# 微信开放平台 / 公众号 Webhook 回调
# ---------------------------------------------------------------------------


def _wechat_webhook_token() -> str:
    return _wechat_cfg("token") or _wechat_cfg("server_token") or _wechat_cfg("webhook_token")


def _wechat_signature_ok(signature: str, timestamp: str, nonce: str, token: str) -> bool:
    if not token:
        return True
    if not signature or not timestamp or not nonce:
        return False
    raw = "".join(sorted([token, timestamp, nonce]))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return secrets.compare_digest(digest, signature)


@router.get("/webhook/wechat")
async def wechat_webhook_verify(
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
):
    """微信服务器回调 URL 验证（GET）。"""
    token = _wechat_webhook_token()
    if token and not _wechat_signature_ok(signature, timestamp, nonce, token):
        raise HTTPException(status_code=403, detail={"message": "微信回调签名校验失败"})
    if echostr:
        return Response(content=echostr, media_type="text/plain")
    return {"success": True, "message": "wechat webhook endpoint active"}


@router.post("/webhook/wechat")
async def wechat_webhook_receive(
    request: Request,
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
):
    """接收微信/公众号推送消息，写入统一收件箱。"""
    from app.services.message_store import push_inbox

    token = _wechat_webhook_token()
    if token and not _wechat_signature_ok(signature, timestamp, nonce, token):
        logger.warning("微信 webhook 签名校验失败: signature=%s timestamp=%s nonce=%s", signature, timestamp, nonce)
        raise HTTPException(status_code=403, detail={"message": "微信回调签名校验失败"})

    content_type = request.headers.get("content-type", "")
    try:
        if "json" in content_type:
            body = await request.json()
        else:
            raw = await request.body()
            raw_text = raw.decode("utf-8", errors="replace")
            body = _parse_wecom_xml(raw_text) if "<xml" in raw_text else {}
    except Exception as exc:
        logger.warning("微信 webhook 解析失败: %s", exc)
        return Response(content="success", media_type="text/plain")

    msg_type = str(body.get("MsgType", body.get("msgtype", "")))
    from_user = str(body.get("FromUserName", body.get("from_user_name", body.get("openid", ""))))
    to_user = str(body.get("ToUserName", body.get("to_user_name", "")))
    msg_id = str(body.get("MsgId", body.get("msg_id", "")))
    content = str(body.get("Content", body.get("content", "")))
    content_kind = "text"

    if not content:
        if msg_type == "event":
            event = str(body.get("Event", body.get("event", "")))
            event_key = str(body.get("EventKey", body.get("event_key", "")))
            content = f"[事件: {event}]" + (f" {event_key}" if event_key else "")
        elif msg_type == "image":
            content = str(body.get("PicUrl", body.get("MediaId", ""))) or "[图片消息]"
            content_kind = "image"
        elif msg_type == "voice":
            content = str(body.get("Recognition", body.get("MediaId", ""))) or "[语音消息]"
            content_kind = "audio"
        elif msg_type == "video":
            content = str(body.get("MediaId", "")) or "[视频消息]"
            content_kind = "video"
        elif msg_type:
            content = f"[微信消息: {msg_type}]"

    if content and from_user:
        push_inbox(
            "wechat",
            contact_id=from_user,
            contact_name=from_user,
            direction="inbound",
            content=content,
            content_type=content_kind,
            metadata={
                "msg_type": msg_type,
                "to_user": to_user,
                "msg_id": msg_id,
                "raw": body,
            },
            msg_id=f"wechat:{msg_id}" if msg_id else None,
        )
        logger.info("微信 webhook 收到消息: from=%s, type=%s, content=%.100s", from_user, msg_type, content)

    return Response(content="success", media_type="text/plain")


# ---------------------------------------------------------------------------
# 企微 Webhook 回调
# ---------------------------------------------------------------------------


@router.api_route("/webhook/wework", methods=["GET", "POST"])
async def wecom_webhook_receive(
    request: Request,
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
):
    """企业微信数据回调：验签、AES 解密并写入统一收件箱。"""
    from fastapi.responses import PlainTextResponse

    from app.services.message_store import push_inbox
    from app.services.wework_suite import (
        WeWorkSuiteError,
        decrypt_callback,
        parse_encrypted_xml,
        parse_plain_event,
        verify_signature,
    )

    try:
        if request.method == "GET":
            verify_signature(msg_signature, timestamp, nonce, echostr)
            return PlainTextResponse(decrypt_callback(echostr, validate_suite_id=False))

        raw = await request.body()
        encrypted = parse_encrypted_xml(raw)
        verify_signature(msg_signature, timestamp, nonce, encrypted)
        body = parse_plain_event(decrypt_callback(encrypted, validate_suite_id=False))
    except WeWorkSuiteError as exc:
        logger.warning("企微数据回调验签/解密失败: %s", exc)
        return PlainTextResponse(str(exc), status_code=400)

    msg_type = body.get("MsgType", body.get("msgtype", ""))
    from_user = str(body.get("FromUserName", body.get("from_user_name", "")))
    content = str(body.get("Content", body.get("content", "")))
    agent_id = str(body.get("AgentID", body.get("agent_id", "")))

    if not content and msg_type == "event":
        # 事件消息，记录事件类型
        event = body.get("Event", body.get("event", ""))
        content = f"[事件: {event}]"

    if not content:
        return PlainTextResponse("success")

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
    return PlainTextResponse("success")


def _parse_wecom_xml(xml_text: str) -> dict:
    """简易微信/企微 XML 解析（不依赖 lxml）。"""
    import re
    import xml.etree.ElementTree as ET

    result: dict[str, str] = {}
    try:
        root = ET.fromstring(xml_text.strip())
        for child in list(root):
            result[str(child.tag)] = (child.text or "").strip()
        if result:
            return result
    except Exception:
        pass

    # 匹配 <Tag>value</Tag> 或 <Tag><![CDATA[value]]></Tag>
    pattern = re.compile(r"<(\w+)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</\1>", re.DOTALL)
    for match in pattern.finditer(xml_text):
        key, value = match.group(1), match.group(2).strip()
        if key != "xml":
            result[key] = value
    return result
