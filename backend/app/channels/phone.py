"""电话 / 短信渠道适配器（真实 HTTP API · 可插拔网关）。

支持两种短信网关：
- Twilio（KELLAI_SMS_PROVIDER=twilio）：account_sid + auth_token + from_number
- 阿里云短信（KELLAI_SMS_PROVIDER=aliyun）：access_key_id + access_key_secret + sign_name + template_code

接收：
- 来电：依赖网关 webhook → 写入 kellai_channel_inbox
- 上行短信：依赖网关 webhook → 写入 kellai_channel_inbox

环境变量：
- KELLAI_SMS_PROVIDER：twilio | aliyun
- KELLAI_SMS_ACCOUNT_SID / KELLAI_SMS_AUTH_TOKEN（twilio）
- KELLAI_SMS_FROM_NUMBER（twilio 发送号码）
- KELLAI_SMS_ACCESS_KEY_ID / KELLAI_SMS_ACCESS_KEY_SECRET / KELLAI_SMS_SIGN_NAME / KELLAI_SMS_TEMPLATE_CODE（aliyun）
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.http_client import read_env

logger = logging.getLogger(__name__)


_UNCONFIGURED_MSG = "电话/短信渠道未配置（设置 KELLAI_SMS_PROVIDER + 对应凭据）"


def _now_ms() -> int:
    return int(time.time() * 1000)


class PhoneAdapter(ChannelAdapter):
    """电话/短信渠道适配器。"""

    channel_type = "phone"

    def __init__(self) -> None:
        self._provider: str = read_env("KELLAI_SMS_PROVIDER", "twilio").lower()
        # Twilio
        self._account_sid: str = read_env("KELLAI_SMS_ACCOUNT_SID")
        self._auth_token: str = read_env("KELLAI_SMS_AUTH_TOKEN")
        self._from_number: str = read_env("KELLAI_SMS_FROM_NUMBER")
        # 阿里云
        self._access_key_id: str = read_env("KELLAI_SMS_ACCESS_KEY_ID")
        self._access_key_secret: str = read_env("KELLAI_SMS_ACCESS_KEY_SECRET")
        self._sign_name: str = read_env("KELLAI_SMS_SIGN_NAME")
        self._template_code: str = read_env("KELLAI_SMS_TEMPLATE_CODE")
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
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}
        content = (content or "").strip()
        if not content:
            return {"success": False, "message_id": "", "error": "消息内容为空"}
        if not contact_id:
            return {"success": False, "message_id": "", "error": "contact_id (手机号) 不能为空"}

        try:
            if self._provider == "twilio":
                return await self._send_twilio(contact_id, content)
            if self._provider == "aliyun":
                return await self._send_aliyun(contact_id, content, kwargs)
            return {"success": False, "message_id": "", "error": f"不支持的 provider: {self._provider}"}
        except Exception as exc:
            logger.warning("短信发送异常: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    async def _send_twilio(self, to: str, body: str) -> dict:
        """Twilio Programmable SMS API。"""
        client = await self._get_client()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json"
        resp = await client.post(
            url,
            auth=(self._account_sid, self._auth_token),
            data={"From": self._from_number, "To": to, "Body": body},
        )
        try:
            result = resp.json()
        except Exception:
            result = {"raw": resp.text}
        if resp.status_code >= 400:
            return {
                "success": False,
                "message_id": "",
                "error": f"Twilio HTTP {resp.status_code}: {result.get('message', result)}",
            }
        return {
            "success": True,
            "message_id": str(result.get("sid", "")),
            "error": "",
        }

    async def _send_aliyun(self, to: str, body: str, kwargs: dict) -> dict:
        """阿里云短信 SendSms API（v1 简化签名版）。"""
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
            "TemplateParam": str(kwargs.get("template_param", json_dumps_safe({"content": body}))),
            "Timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        resp = await client.get("https://dysmsapi.aliyuncs.com/", params=params)
        try:
            result = resp.json()
        except Exception:
            result = {"raw": resp.text}
        if str(result.get("Code", "")).upper() != "OK":
            return {
                "success": False,
                "message_id": "",
                "error": f"阿里云短信失败: {result.get('Code')} {result.get('Message')}",
            }
        return {
            "success": True,
            "message_id": str(result.get("RequestId", "")),
            "error": "",
        }

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        """从收件箱表读取（webhook 已写入：来电/上行短信）。"""
        try:
            from app.services.message_store import list_inbox
            rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取电话收件箱失败: %s", exc)
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

    async def test_connection(self) -> dict:
        if not self._is_configured():
            return {"connected": False, "message": _UNCONFIGURED_MSG}
        if self._provider == "twilio":
            return {"connected": True, "message": f"Twilio 已配置（from={self._from_number}）"}
        if self._provider == "aliyun":
            return {"connected": True, "message": f"阿里云短信已配置（sign={self._sign_name}, template={self._template_code}）"}
        return {"connected": False, "message": f"未知 provider: {self._provider}"}


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
