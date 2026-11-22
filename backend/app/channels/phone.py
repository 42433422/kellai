"""短信渠道适配器（沿用历史类型 phone；不提供语音外呼）。

支持两种短信网关：
- Twilio（KELLAI_SMS_PROVIDER=twilio）：account_sid + auth_token + from_number
- 阿里云短信（KELLAI_SMS_PROVIDER=aliyun）：access_key_id + access_key_secret + sign_name + template_code

原生上行短信和送达回调尚未接入。双向短信可使用 Chatwoot 短信收件箱。

环境变量：
- KELLAI_SMS_PROVIDER：twilio | aliyun
- KELLAI_SMS_ACCOUNT_SID / KELLAI_SMS_AUTH_TOKEN（twilio）
- KELLAI_SMS_FROM_NUMBER（twilio 发送号码）
- KELLAI_SMS_ACCESS_KEY_ID / KELLAI_SMS_ACCESS_KEY_SECRET / KELLAI_SMS_SIGN_NAME / KELLAI_SMS_TEMPLATE_CODE（aliyun）
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.config_store import get_field
from app.channels.http_client import read_env, checked_json, send_error, check_send_authorization

logger = logging.getLogger(__name__)


_UNCONFIGURED_MSG = "短信渠道未配置，请在渠道管理选择 Twilio 或阿里云并保存对应凭据"

PHONE_CONFIG_SCHEMA = {
    "type": "object",
    "required": ["provider"],
    "oneOf": [
        {"properties": {"provider": {"const": "twilio"}},
         "required": ["account_sid", "auth_token", "from_number"]},
        {"properties": {"provider": {"const": "aliyun"}},
         "required": ["access_key_id", "access_key_secret", "sign_name", "template_code"]},
    ],
    "properties": {
        "provider": {"type": "string", "title": "短信服务商", "enum": ["twilio", "aliyun"],
                     "default": "twilio", "x-enum-labels": {"twilio": "Twilio 文本短信", "aliyun": "阿里云模板短信"}},
        "account_sid": {"type": "string", "title": "Twilio Account SID", "x-providers": ["twilio"]},
        "auth_token": {"type": "string", "title": "Twilio Auth Token", "writeOnly": True, "x-providers": ["twilio"]},
        "from_number": {"type": "string", "title": "Twilio 发送号码", "x-providers": ["twilio"],
                        "description": "使用已开通短信能力的号码，按 E.164 格式填写，例如 +15551234567。"},
        "access_key_id": {"type": "string", "title": "阿里云 AccessKey ID", "x-providers": ["aliyun"]},
        "access_key_secret": {"type": "string", "title": "阿里云 AccessKey Secret", "writeOnly": True, "x-providers": ["aliyun"]},
        "sign_name": {"type": "string", "title": "已审核短信签名", "x-providers": ["aliyun"]},
        "template_code": {"type": "string", "title": "已审核模板 CODE", "x-providers": ["aliyun"],
                          "description": "例如 SMS_123456789。发送需显式模板参数；当前消息界面只发送自由文本，尚未接入模板编辑。"},
    },
}


def phone_required_fields(provider: str) -> list[str]:
    fields = list(PHONE_CONFIG_SCHEMA["required"])
    for branch in PHONE_CONFIG_SCHEMA["oneOf"]:
        if branch["properties"]["provider"]["const"] == provider:
            return fields + branch["required"]
    return fields


def phone_capabilities(base: dict[str, Any]) -> dict[str, Any]:
    """A configured template gateway must not enter the generic text sender."""
    provider = get_field("phone", "provider", "twilio").strip().lower()
    capabilities = dict(base)
    capabilities["provider"] = provider
    capabilities["message_types"] = ["text"] if provider == "twilio" else ["template"]
    if provider == "aliyun":
        capabilities["limitations"] = [
            "阿里云仅支持已审核签名和模板，发送必须提供匹配的 template_param；模板发送界面尚未实现。",
            *base.get("limitations", []),
        ]
    elif provider != "twilio":
        capabilities.update(send=False, readiness="blocked")
    return capabilities


def _now_ms() -> int:
    return int(time.time() * 1000)


class PhoneAdapter(ChannelAdapter):
    """Twilio 文本短信 / 阿里云显式模板短信。"""

    channel_type = "phone"

    def __init__(self) -> None:
        self._provider: str = get_field("phone", "provider", "twilio").strip().lower()
        # Twilio
        self._account_sid: str = get_field("phone", "account_sid")
        self._auth_token: str = get_field("phone", "auth_token")
        self._from_number: str = get_field("phone", "from_number")
        # 阿里云
        self._access_key_id: str = get_field("phone", "access_key_id")
        self._access_key_secret: str = get_field("phone", "access_key_secret")
        self._sign_name: str = get_field("phone", "sign_name")
        self._template_code: str = get_field("phone", "template_code")
        self._client: httpx.AsyncClient | None = None

    def _is_configured(self) -> bool:
        if self._provider == "twilio":
            return bool(self._account_sid and self._auth_token and self._from_number)
        if self._provider == "aliyun":
            return bool(
                self._access_key_id
                and self._access_key_secret
                and self._sign_name
                and self._template_code
            )
        return False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    # ----------------- send_message -----------------

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        """发送短信到 contact_id（手机号）。"""
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG, "delivery_state": "failed", "definitely_not_sent": True}
        content = (content or "").strip()
        if not content and self._provider == "twilio":
            return {"success": False, "message_id": "", "error": "消息内容为空", "delivery_state": "failed", "definitely_not_sent": True}
        if not contact_id:
            return {"success": False, "message_id": "", "error": "contact_id (手机号) 不能为空", "delivery_state": "failed", "definitely_not_sent": True}

        try:
            if self._provider == "twilio":
                return await self._send_twilio(contact_id, content, kwargs.get("before_send"))
            if self._provider == "aliyun":
                return await self._send_aliyun(contact_id, content, kwargs)
            return {"success": False, "message_id": "", "error": f"不支持的 provider: {self._provider}", "delivery_state": "failed", "definitely_not_sent": True}
        except Exception as exc:
            logger.warning("短信发送异常: %s", type(exc).__name__)
            return send_error(exc)

    async def _send_twilio(self, to: str, body: str, before_send) -> dict:
        """Twilio Programmable SMS API。"""
        client = await self._get_client()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json"
        check_send_authorization(before_send)
        resp = await client.post(
            url,
            auth=(self._account_sid, self._auth_token),
            data={"From": self._from_number, "To": to, "Body": body},
        )
        result = checked_json(resp)
        if not result.get("sid"):
            return send_error("Twilio 未返回消息SID，发送结果未知")
        if result.get("status") in {"failed", "undelivered"}:
            return send_error("Twilio 消息发送失败", definitely_not_sent=True)
        return {"success": True, "message_id": str(result["sid"]),
                "delivery_state": "accepted", "error": ""}

    async def _send_aliyun(self, to: str, body: str, kwargs: dict) -> dict:
        """阿里云短信 SendSms API（v1 简化签名版）。"""
        template_param = kwargs.get("template_param")
        if template_param is None:
            return send_error("阿里云仅支持已审核模板，需显式 template_param；当前通用文本界面尚未接入模板发送",
                              definitely_not_sent=True)
        try:
            if isinstance(template_param, str):
                template_param = json.loads(template_param)
            if not isinstance(template_param, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in template_param.items()
            ):
                raise ValueError("template variables must be strings")
            encoded_template = json_dumps_safe(template_param)
        except (TypeError, ValueError):
            return send_error("template_param 必须是变量名和值均为字符串的 JSON 对象；无变量模板请显式传 {}",
                              definitely_not_sent=True)
        params = {
            "AccessKeyId": self._access_key_id,
            "Action": "SendSms",
            "Format": "JSON",
            "PhoneNumbers": to,
            "SignName": self._sign_name,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "TemplateCode": self._template_code,
            "TemplateParam": encoded_template,
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Version": "2017-05-25",
        }
        # 拼接 + 签名
        sorted_items = sorted(params.items())
        canonical = "&".join(_percent_encode(k) + "=" + _percent_encode(str(v)) for k, v in sorted_items)
        string_to_sign = "GET&" + _percent_encode("/") + "&" + _percent_encode(canonical)
        signature = hmac.new(
            (self._access_key_secret + "&").encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        import base64
        params["Signature"] = base64.b64encode(signature).decode("utf-8")

        client = await self._get_client()
        check_send_authorization(kwargs.get("before_send"))
        resp = await client.get("https://dysmsapi.aliyuncs.com/", params=params)
        result = checked_json(resp)
        if str(result.get("Code", "")).upper() != "OK":
            return send_error("阿里云短信请求失败",
                              definitely_not_sent="Code" in result)
        if not result.get("BizId"):
            return send_error("阿里云未返回短信 BizId，发送结果未知")
        return {
            "success": True,
            "message_id": str(result.get("BizId", "")),
            "delivery_state": "accepted",
            "error": "",
        }

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        """消费历史本地收件箱；此适配器尚无原生上行短信入口。"""
        try:
            from app.services.message_store import list_inbox
            rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取电话收件箱失败: %s", type(exc).__name__)
            return []
        out: list[UnifiedMessage] = []
        for r in rows:
            created_at = str(r.get("received_at", ""))
            if since and created_at and created_at <= since:
                continue
            out.append(
                UnifiedMessage(
                    id=str(r["id"]),
                    customer_id=0,
                    channel_type=self.channel_type,
                    contact_id=str(r.get("contact_id", "")),
                    contact_name=str(r.get("contact_name", "")),
                    direction=str(r.get("direction", "inbound")),
                    content=str(r.get("content", "")),
                    content_type=str(r.get("content_type", "text")),
                    metadata=dict(r.get("metadata", {}) or {}),
                    created_at=created_at or datetime.now(timezone.utc).isoformat(),
                )
            )
        return out

    # ----------------- get_contacts -----------------

    async def get_contacts(self, keyword: str = "", limit: int = 80) -> list[dict]:
        """电话渠道联系人：基于历史收件箱聚合。"""
        try:
            from app.services.message_store import list_inbox
            rows = list_inbox(self.channel_type, limit=500, include_consumed=True)
        except Exception:
            return []
        seen: dict[str, dict] = {}
        for r in rows:
            cid = str(r.get("contact_id", "")).strip()
            if not cid or cid in seen:
                continue
            seen[cid] = {
                "id": cid,
                "name": str(r.get("contact_name", "")) or cid,
                "channel": self.channel_type,
            }
            if keyword and keyword not in seen[cid]["name"]:
                seen.pop(cid)
                continue
            if len(seen) >= int(limit):
                break
        return list(seen.values())

    # ----------------- test_connection -----------------

    async def test_connection(self, **kwargs) -> dict:
        if not self._is_configured():
            return {"connected": False, "message": _UNCONFIGURED_MSG}
        if self._provider == "twilio":
            try:
                client = await self._get_client()
                body = checked_json(await client.get(
                    f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}.json",
                    auth=(self._account_sid, self._auth_token),
                ))
                if body.get("sid") != self._account_sid:
                    raise ValueError("Twilio账号不匹配")
                return {"connected": True, "verification_level": "authenticated",
                        "message": "Twilio账号鉴权通过；尚未进行真实短信收发验收"}
            except Exception as exc:
                return {"connected": False, "message": f"Twilio鉴权失败: {type(exc).__name__}"}
        return {"connected": False, "verification_level": "configured",
                "message": "阿里云模板短信凭据已配置；尚未进行远端鉴权及真实发送验收"}



# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _percent_encode(s: str) -> str:
    """阿里云 v1 API 签名用的 percent-encode。"""
    from urllib.parse import quote
    return quote(str(s), safe="~")


def json_dumps_safe(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
