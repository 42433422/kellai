"""客来来 HTTP API（自 xcagi-customer-service-bridge user-cs 路由复制 · 独立前缀）。"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
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
        connected = enabled and has_config
        result.append({
            "id": f"ch_{ch['channel_type']}",
            "name": cfg.get("name") or ch["channel_type"],
            "type": ch["channel_type"],
            "adapter_class": ch["adapter_class"],
            "enabled": enabled,
            "connected": connected,
            "message": "已保存配置，点击测试连接验证" if connected else "未配置",
            "config": merged_config,
            "config_schema": ch.get("config_schema") or {},
            "createdAt": cfg.get("createdAt") or "",
        })
    return {"success": True, "data": result}


@router.post("/channels/{channel_type}/test")
async def test_channel(channel_type: str):
    """测试指定渠道连接。"""
    from app.channels import ChannelRegistry

    reg = ChannelRegistry()
    try:
        adapter = reg.get(channel_type)
    except KeyError:
        return {"success": False, "error": f"未注册的渠道类型: {channel_type}"}
    try:
        result = await adapter.test_connection()
    except Exception as exc:
        return {"success": False, "error": f"测试失败: {exc}"}
    return {
        "success": bool(result.get("connected")),
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
    )
    logger.info("渠道配置已保存: %s (enabled=%s)", channel_type, saved.get("enabled"))
    return {
        "success": True,
        "data": {
            "id": f"ch_{channel_type}",
            "name": saved.get("name", channel_type),
            "type": channel_type,
            "enabled": bool(saved.get("enabled")),
            "config": saved.get("config", {}),
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
    from app.services.message_store import get_messages as _get_messages
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
        messages.sort(key=lambda m: m.created_at, reverse=True)
        messages = messages[:limit]

    return {
        "success": True,
        "data": [msg.model_dump() for msg in messages],
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
    save_message(msg)
    return {"success": result.get("success", False), "data": {"message_id": msg.id, "channel_result": result}}


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


@router.get("/ai/reminders")
async def ai_reminders(
    hours: int = 48,
    limit: int = 20,
    _rl: None = Depends(enforce_llm_rate_limit),
):
    """获取跟进提醒列表"""
    from app.services.ai_copilot import get_follow_up_reminders

    reminders = get_follow_up_reminders(hours_threshold=hours)
    return {"success": True, "data": {"reminders": reminders[:limit]}}


@router.post("/ai/score/{customer_id}")
async def ai_update_score(
    customer_id: int,
    request: Request,
    _rl: None = Depends(enforce_llm_rate_limit),
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
