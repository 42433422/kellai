"""Authenticated WeChat/WeCom callback glue for the existing durable inbox.

No callback chooses its tenant from an unverified body. WeChat uses a scoped
URL and a saved tenant token; WeCom uses its verified decrypted corporation ID
and the existing third-party authorization registry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Any

from app.services.tenant_context import resolve_team_id, tenant_scope

logger = logging.getLogger(__name__)
MAX_CALLBACK_BYTES = 1024 * 1024


class WechatIngressError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def legacy_wechat_team() -> int:
    """The old URL is usable only after an operator binds it to one team."""

    try:
        team_id = int(os.environ.get("KELLAI_WECHAT_WEBHOOK_TEAM_ID", "0"))
        return resolve_team_id(team_id, required=True)
    except (ValueError, PermissionError) as exc:
        raise WechatIngressError("微信回调未绑定团队，请使用团队专属回调地址", 403) from exc


def wechat_config(team_id: int) -> dict[str, str]:
    from app.channels.config_store import get

    try:
        team_id = resolve_team_id(team_id, required=True)
        with tenant_scope(team_id):
            saved = get("wechat")
    except PermissionError as exc:
        raise WechatIngressError("微信回调团队无效", 403) from exc
    # Global environment fallback would let one token authorize every team URL.
    # Tenant callbacks therefore require credentials in that tenant's config.
    fields = {**saved, **(saved.get("config") or {})}
    token = ""
    for name in ("webhook_token", "token", "server_token"):
        if name in fields:
            token = str(fields[name] or "").strip()
            break
    if not token:
        raise WechatIngressError("此团队未配置微信回调 Token", 403)
    return {
        "token": token,
        "original_id": str(fields.get("official_original_id") or fields.get("original_id") or "").strip(),
    }


def verify_wechat_signature(*, signature: str, timestamp: str, nonce: str, token: str) -> None:
    if not token or not signature or not nonce or not timestamp:
        raise WechatIngressError("微信回调签名校验失败", 403)
    try:
        # A provider retry is seconds old. Old captured URL signatures must not
        # remain reusable indefinitely in this plaintext callback mode.
        fresh = abs(time.time() - int(timestamp)) <= 300
    except (ValueError, TypeError):
        fresh = False
    expected = hashlib.sha1("".join(sorted([token, timestamp, nonce])).encode()).hexdigest()
    if not fresh or not hmac.compare_digest(expected, signature):
        raise WechatIngressError("微信回调签名校验失败", 403)


def parse_xml(raw: bytes) -> dict[str, str]:
    if not raw or len(raw) > MAX_CALLBACK_BYTES:
        raise WechatIngressError("回调正文为空或超过大小限制", 413 if raw else 400)
    try:
        xml_text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WechatIngressError("回调 XML 必须为 UTF-8 编码") from exc
    if "\x00" in xml_text or "<!DOCTYPE" in xml_text.upper() or "<!ENTITY" in xml_text.upper():
        raise WechatIngressError("不接受带 DTD 或实体声明的回调 XML")
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError) as exc:
        raise WechatIngressError("回调 XML 无效") from exc
    if root.tag != "xml":
        raise WechatIngressError("回调 XML 根节点无效")
    body: dict[str, str] = {}
    for child in root:
        if child.tag in body:
            raise WechatIngressError("回调 XML 存在重复字段")
        body[child.tag] = (child.text or "").strip() if not len(child) else ET.tostring(child, encoding="unicode")
    return body


def stable_message_id(channel_type: str, body: dict[str, str]) -> str:
    """MsgId deduplication, or canonical event identity when no MsgId exists."""

    provider_id = str(body.get("MsgId") or "")
    identity: Any = [body.get("ToUserName", ""), provider_id] if provider_id else body
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")).encode()).hexdigest()
    return f"{channel_type}:{'message' if provider_id else 'event'}:{digest}"


def _message_content(body: dict[str, str]) -> tuple[str, str]:
    kind = str(body.get("MsgType") or "").lower()
    if kind == "text":
        content = str(body.get("Content") or "")
        if not content.strip():
            raise WechatIngressError("文本回调缺少消息内容")
        return content, "text"
    if kind == "event":
        event = str(body.get("Event") or "")
        if not event:
            raise WechatIngressError("事件回调缺少事件类型")
        event_key = str(body.get("EventKey") or "")
        return f"[事件: {event}]" + (f" {event_key}" if event_key else ""), "event"
    if not kind:
        raise WechatIngressError("回调缺少消息类型")
    types = {"image": "image", "voice": "audio", "video": "video", "shortvideo": "video", "file": "file"}
    return str(body.get("Recognition") or body.get("PicUrl") or body.get("MediaId") or f"[{kind} 消息]"), types.get(kind, "unsupported")


def persist_callback(*, channel_type: str, team_id: int, body: dict[str, str]) -> str:
    from app.services.message_store import push_inbox

    team_id = resolve_team_id(team_id, required=True)
    to_user = str(body.get("ToUserName") or "").strip()
    from_user = str(body.get("FromUserName") or "").strip()
    if not to_user or not str(body.get("CreateTime") or "").isdigit():
        raise WechatIngressError("回调缺少接收帐号或消息创建时间")
    content, content_type = _message_content(body)
    if not from_user and content_type == "event" and channel_type == "wework":
        from_user = str(body.get("ExternalUserID") or body.get("UserID") or f"event:{to_user}")
    if not from_user:
        raise WechatIngressError("回调缺少发送人")
    metadata = {
        "team_id": team_id,
        "msg_type": str(body.get("MsgType") or ""),
        "to_user": to_user,
        "msg_id": str(body.get("MsgId") or ""),
        "agent_id": str(body.get("AgentID") or ""),
        "event": str(body.get("Event") or ""),
        "event_key": str(body.get("EventKey") or ""),
        "provider_created_at": str(body.get("CreateTime") or ""),
        "source": "verified_callback",
    }
    with tenant_scope(team_id):
        return push_inbox(channel_type, contact_id=from_user, contact_name=from_user,
                          direction="inbound", content=content, content_type=content_type,
                          metadata=metadata, msg_id=stable_message_id(channel_type, body), team_id=team_id)


async def sync_persisted_callback(*, team_id: int, channel_type: str) -> None:
    """The durable inbox remains retryable if CRM or enqueue is unavailable."""

    from app.services.channel_ingest import sync_inbox

    try:
        await sync_inbox(team_id=team_id, channel_type=channel_type)
    except Exception:
        logger.exception("已保存渠道回调，接入待重试: team=%s channel=%s", team_id, channel_type)
