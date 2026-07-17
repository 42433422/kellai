"""微信开放平台 / 公众号渠道适配器。

支持三条互补路径：
- 微信开放平台网站应用 OAuth：扫码授权后保存 openid/unionid，作为客户身份绑定依据
- 公众号客服消息：配置公众号 AppID/Secret 后，通过客服接口向 openid 发文本消息
- 旧版群机器人 Webhook：继续兼容 KELLAI_WECHAT_BOT_WEBHOOK 或前端保存的 bot_webhook

接收侧统一复用 kellai_channel_inbox，微信回调写入后由这里消费。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.config_store import get_field
from app.channels.http_client import BaseChannelClient, CachedToken, read_env

logger = logging.getLogger(__name__)

_UNCONFIGURED_MSG = "微信渠道未配置（缺少开放平台 AppID/Secret、公众号 AppID/Secret 或 bot_webhook）"


def _cfg(field: str, default: str = "") -> str:
    value = get_field("wechat", field, default=default)
    if value:
        return value
    suffix = field.upper()
    return (
        read_env(f"KELLAI_WECHAT_{suffix}", default=default)
        or read_env(f"WECHAT_{suffix}", default=default)
    )


def _cfg_any(*fields: str) -> str:
    for field in fields:
        value = _cfg(field)
        if value:
            return value
    return ""


class _WeChatOfficialClient(BaseChannelClient):
    """微信公众号 HTTP 客户端。"""

    _base_url = "https://api.weixin.qq.com"

    def __init__(self, app_id: str, app_secret: str) -> None:
        super().__init__()
        self._app_id = app_id
        self._app_secret = app_secret
        self._token: CachedToken | None = None

    def ensure_token(self) -> CachedToken:
        if self._token is None:
            if not self._app_id or not self._app_secret:
                raise RuntimeError("缺少公众号 AppID/Secret")
            self._token = CachedToken(self._fetch_token, ttl_sec=7000)
        return self._token

    async def _fetch_token(self) -> tuple[str, int]:
        body = await self.get_json(
            "/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": self._app_id,
                "secret": self._app_secret,
            },
        )
        token = str(body.get("access_token", ""))
        ttl = int(body.get("expires_in", 7200) or 7200)
        if not token:
            raise RuntimeError("微信 gettoken 返回空 access_token")
        return token, ttl

    async def _on_token_invalid(self) -> None:
        if self._token is not None:
            self._token.invalidate()

    async def fetch_token(self) -> str:
        return await self.ensure_token().get()

    async def post_with_token(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = await self.fetch_token()
        return await self.post_json(path, params={"access_token": token}, json=payload)


class WeChatAdapter(ChannelAdapter):
    """微信开放平台 / 公众号渠道适配器。"""

    channel_type = "wechat"

    def _app_id(self) -> str:
        return _cfg_any("app_id", "appid")

    def _app_secret(self) -> str:
        return _cfg_any("app_secret", "secret", "appsecret")

    def _official_app_id(self) -> str:
        return _cfg_any("official_app_id", "mp_app_id", "app_id", "appid")

    def _official_app_secret(self) -> str:
        return _cfg_any("official_app_secret", "mp_app_secret", "app_secret", "secret", "appsecret")

    def _bot_webhook(self) -> str:
        return _cfg("bot_webhook")

    def _oauth_openid(self) -> str:
        return _cfg("oauth_openid")

    def _oauth_authorized(self) -> bool:
        return _cfg("oauth_authorized").lower() in {"1", "true", "yes", "ok"}

    def _has_official_account_config(self) -> bool:
        return bool(
            _cfg_any("official_app_id", "mp_app_id")
            and _cfg_any("official_app_secret", "mp_app_secret")
        )

    def _is_configured(self) -> bool:
        if self._bot_webhook():
            return True
        if self._has_official_account_config():
            return True
        if self._app_id() and self._app_secret():
            return True
        if self._oauth_authorized() and self._oauth_openid():
            return True
        return False

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}

        content = (content or "").strip()
        if not content:
            return {"success": False, "message_id": "", "error": "消息内容为空"}
        if not contact_id:
            return {"success": False, "message_id": "", "error": "contact_id/openid 不能为空"}

        if self._bot_webhook() and contact_id.startswith("@chat"):
            return await self._send_via_bot(content, kwargs.get("mentioned_list", []))

        if self._has_official_account_config():
            return await self._send_via_customer_service(contact_id, content)

        if self._oauth_authorized() and self._oauth_openid():
            return {
                "success": False,
                "message_id": "",
                "error": "微信开放平台 OAuth 已授权，可识别 openid/unionid；主动发消息还需配置公众号 AppID/Secret 并开通客服消息接口",
            }

        if self._bot_webhook():
            return await self._send_via_bot(content, kwargs.get("mentioned_list", []))

        return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}

    async def _send_via_bot(self, content: str, mentioned: list[str]) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.post(
                    self._bot_webhook(),
                    json={
                        "msgtype": "markdown",
                        "markdown": {"content": content},
                        "mentioned_list": list(mentioned or []),
                    },
                )
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            if resp.status_code >= 400 or int(body.get("errcode", 0)) != 0:
                return {
                    "success": False,
                    "message_id": "",
                    "error": f"微信机器人返回错误: HTTP {resp.status_code} body={body}",
                }
            return {
                "success": True,
                "message_id": str(body.get("msgid", "")),
                "error": "",
            }
        except Exception as exc:
            logger.warning("微信 send_message 失败: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    async def _send_via_customer_service(self, openid: str, content: str) -> dict:
        try:
            client = _WeChatOfficialClient(self._official_app_id(), self._official_app_secret())
            body = await client.post_with_token(
                "/cgi-bin/message/custom/send",
                {
                    "touser": openid,
                    "msgtype": "text",
                    "text": {"content": content},
                },
            )
            return {
                "success": True,
                "message_id": str(body.get("msgid", "")),
                "error": "",
            }
        except Exception as exc:
            logger.warning("微信客服消息发送失败: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        try:
            from app.services.message_store import list_inbox

            rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取微信收件箱失败: %s", exc)
            return []

        messages: list[UnifiedMessage] = []
        for row in rows:
            created_at = str(row.get("received_at", ""))
            if since and created_at and created_at <= since:
                continue
            messages.append(
                UnifiedMessage(
                    id=str(row["id"]),
                    customer_id=0,
                    channel_type=self.channel_type,
                    contact_id=str(row.get("contact_id", "")),
                    contact_name=str(row.get("contact_name", "")),
                    direction=str(row.get("direction", "inbound")),
                    content=str(row.get("content", "")),
                    content_type=str(row.get("content_type", "text")),
                    metadata=dict(row.get("metadata", {}) or {}),
                    created_at=created_at or datetime.now(timezone.utc).isoformat(),
                )
            )
        return messages

    async def get_contacts(self, keyword: str = "", limit: int = 80) -> list[dict]:
        try:
            from app.services.message_store import list_inbox

            rows = list_inbox(self.channel_type, limit=500, include_consumed=True)
        except Exception:
            return []

        seen: dict[str, dict] = {}
        kw = keyword.lower()
        for row in rows:
            cid = str(row.get("contact_id", "")).strip()
            if not cid or cid in seen:
                continue
            name = str(row.get("contact_name", "")).strip() or cid
            if kw and kw not in name.lower() and kw not in cid.lower():
                continue
            seen[cid] = {"id": cid, "name": name, "channel": self.channel_type}
            if len(seen) >= int(limit):
                break
        return list(seen.values())

    async def test_connection(self) -> dict:
        if not self._is_configured():
            return {"connected": False, "message": _UNCONFIGURED_MSG}
        if self._bot_webhook():
            return {"connected": True, "message": "微信兼容 Webhook 已配置（无需 access_token）"}
        if self._has_official_account_config():
            try:
                client = _WeChatOfficialClient(self._official_app_id(), self._official_app_secret())
                token = await client.fetch_token()
                if token:
                    return {"connected": True, "message": "微信公众号 access_token 拉取成功，客服消息接口可用"}
                return {"connected": False, "message": "微信公众号 token 为空"}
            except Exception as exc:
                return {"connected": False, "message": f"微信公众号连接失败: {exc}"}
        if self._oauth_authorized() and self._oauth_openid():
            return {"connected": True, "message": f"微信开放平台 OAuth 已授权（openid={self._oauth_openid()}）"}
        if self._app_id() and self._app_secret():
            return {"connected": False, "message": "微信开放平台 AppID/Secret 已保存，请扫码授权完成接入"}
        return {"connected": False, "message": _UNCONFIGURED_MSG}
