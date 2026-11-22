"""Audited implementation capabilities, not proof of a customer's authorization.

Only an actual end-to-end receipt can establish live delivery. The catalog is
the shared backend/frontend source of truth and never infers ability from a name.
"""
from __future__ import annotations

from typing import Any


def _cap(*, receive: bool, send: bool, transport: str, receive_mode: str,
         readiness: str, limitations: list[str], auto_reply: bool = True, **extra: Any) -> dict:
    return {"receive": receive, "send": send, "contacts": True, "sync": True,
            "transport": transport, "receive_mode": receive_mode, "readiness": readiness,
            "auto_reply": False,
            "verification_level": "code_reviewed", "live_verified": False,
            "contact_source": "known_contacts", "limitations": limitations, **extra}


CAPABILITIES = {
    "wework": _cap(receive=True, send=True, transport="api", receive_mode="signed_webhook",
        readiness="implemented", limitations=[
            "应用消息仅发内部成员；群机器人发固定群；客服接待链接不等于外部联系人聊天API。",
            "需要企业授权、应用可见范围和可信回调；尚无该账号真实送达验收。"],
        send_modes=["internal_app_message", "fixed_group_bot"]),
    "wechat": _cap(receive=True, send=True, transport="api", receive_mode="signed_webhook",
        readiness="implemented", limitations=[
            "当前公众号回调仅明文模式，AES安全模式尚未接入。",
            "公众号客服消息需要公众号权限、openid及平台回复窗口。",
            "开放平台扫码登录只证明身份授权；不支持个人微信好友任意私聊。"],
        send_modes=["official_account_customer_service", "fixed_group_bot"]),
    "douyin": _cap(receive=True, send=True, transport="api", receive_mode="signed_webhook",
        readiness="conditional", limitations=[
            "仅官方企业号私信API；需要对应scope、已绑定openid与真实入站会话。",
            "历史集中桥接、第三方门户和坐标发送已移除，需重新授权明确账号。"],
        message_types=["text"]),
    "miniprogram": _cap(receive=False, send=True, transport="api", receive_mode="local_inbox_only",
        readiness="outbound_only", auto_reply=False, limitations=[
            "这里只实现用户订阅的模板通知，不是任意文本私聊；需要template_id和匹配的模板字段。",
            "原生云函数入站适配尚未提供。"], message_types=["template"]),
    "phone": _cap(receive=False, send=True, transport="sms_api", receive_mode="local_inbox_only",
        readiness="outbound_only", auto_reply=False, limitations=[
            "现有实现为Twilio短信/阿里云模板短信，不是语音通话。",
            "原生上行短信和送达回调尚未接入；可通过支持该渠道的Chatwoot收件箱接入。"]),
    "telegram": _cap(receive=False, send=True, transport="api", receive_mode="local_inbox_only",
        readiness="outbound_only", limitations=[
            "Bot API sendMessage可发送到有权限的chat_id；原生getUpdates/webhook尚未实现。",
            "双向消息可使用Chatwoot Telegram收件箱。"]),
    "line": _cap(receive=False, send=True, transport="api", receive_mode="local_inbox_only",
        readiness="outbound_only", limitations=[
            "Messaging API push仅限平台允许的user/group目标；原生签名回调尚未实现。",
            "双向消息可使用Chatwoot LINE收件箱。"]),
    "whatsapp": _cap(receive=False, send=True, transport="api", receive_mode="local_inbox_only",
        readiness="outbound_only", limitations=[
            "Cloud API自由文本受会话窗口及商业账号授权限制；原生回调尚未实现。",
            "双向消息可使用Chatwoot WhatsApp收件箱。"]),
    "chatwoot": _cap(receive=True, send=True, transport="api", receive_mode="api_polling_and_signed_webhook",
        readiness="implemented", limitations=[
            "绑定一个account/inbox；网关支持哪些平台取决于Chatwoot收件箱及该平台账号授权。",
            "发送响应仅表示Chatwoot受理；真实status经认证API读取，未知结果不自动重发。",
            "本机主动分页拉取并持久保存进度；签名回调可选，不要求把桌面端口暴露到公网。",
            "当前客来来适配器只发送文本；平台接入和真实设备验收仍需部署方完成。"],
        upstream_version="4.20.1", message_types=["text"]),
}

for _kind, _reason in {
    "taobao": "旧实现调用TMC事件生产，不是买家私聊。",
    "jd": "旧协议缺少完整OAuth/平台授权，无法证明京麦聊天可用。",
    "pdd": "旧发送请求缺少完整开放平台方法和授权，无法证明客服聊天可用。",
    "alibaba": "旧开放平台请求未形成可验证的旺旺/1688聊天协议。",
}.items():
    CAPABILITIES[_kind] = _cap(receive=False, send=False, transport="unverified",
        receive_mode="local_inbox_only", readiness="blocked", auto_reply=False,
        limitations=[_reason, "保留配置和历史数据；需官方授权协议及真实平台验收后再开放发送。"])


CHATWOOT_CONFIG_SCHEMA = {
    "type": "object",
    "required": ["base_url", "account_id", "inbox_id", "api_access_token"],
    "properties": {
        "base_url": {"type": "string", "title": "Chatwoot 地址"},
        "account_id": {"type": "string", "title": "Account ID"},
        "inbox_id": {"type": "string", "title": "Inbox ID"},
        "api_access_token": {"type": "string", "title": "API Access Token", "writeOnly": True},
        "webhook_secret": {"type": "string", "title": "Webhook Secret（仅接收回调时填写）", "writeOnly": True},
    },
}


def resolve_send_capability(channel_type: str, **kwargs) -> dict:
    return dict(CAPABILITIES.get(channel_type, {"send": False, "transport": "unverified"}))
