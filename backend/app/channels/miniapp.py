"""微信小程序渠道适配器（真实 HTTP API 实现）。

功能：
- 发送订阅消息：POST /cgi-bin/message/subscribe/send
- 服务端 API 鉴权：与公众号/小程序共用 access_token（appid + secret）
- 接收：依赖微信云函数 HTTP 触发 → 写入 kellai_channel_inbox，本接口消费

环境变量：
- KELLAI_MINIAPP_APPID
- KELLAI_MINIAPP_APP_ID（兼容前端字段 app_id）
- KELLAI_MINIAPP_SECRET
- KELLAI_MINIAPP_TEMPLATE_ID（默认订阅消息模板）
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.config_store import get_field
from app.channels.http_client import CachedToken, read_env

logger = logging.getLogger(__name__)


_UNCONFIGURED_MSG = "小程序渠道未配置（缺少 app_id/app_secret）"


def _app_id() -> str:
    return (
        get_field("miniprogram", "app_id")
        or get_field("miniapp", "app_id")
        or read_env("KELLAI_MINIAPP_APPID")
        or read_env("KELLAI_MINIAPP_APP_ID")
        or read_env("KELLAI_MINIPROGRAM_APPID")
        or read_env("KELLAI_MINIPROGRAM_APP_ID")
    )


def _app_secret() -> str:
    return (
        get_field("miniprogram", "app_secret")
        or get_field("miniapp", "app_secret")
        or get_field("miniprogram", "secret")
        or get_field("miniapp", "secret")
        or read_env("KELLAI_MINIAPP_SECRET")
        or read_env("KELLAI_MINIAPP_APP_SECRET")
        or read_env("KELLAI_MINIPROGRAM_SECRET")
        or read_env("KELLAI_MINIPROGRAM_APP_SECRET")
    )


def _template_id() -> str:
    return (
        get_field("miniprogram", "template_id")
        or get_field("miniapp", "template_id")
        or read_env("KELLAI_MINIAPP_TEMPLATE_ID")
        or read_env("KELLAI_MINIPROGRAM_TEMPLATE_ID")
    )


def _inbox_channel_types() -> list[str]:
    return ["miniprogram", "miniapp"]


class MiniAppAdapter(ChannelAdapter):
    """小程序渠道适配器。"""

    channel_type = "miniprogram"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._token: CachedToken | None = None
        self._token_config_key: tuple[str, str] | None = None

    def _is_configured(self) -> bool:
        return bool(_app_id() and _app_secret())

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.weixin.qq.com",
                timeout=15.0,
                headers={"User-Agent": "kellai-miniapp/1.0"},
            )
        return self._client

    async def _fetch_token(self) -> tuple[str, int]:
        client = await self._get_client()
        resp = await client.get(
            "/cgi-bin/token",
            params={"grant_type": "client_credential", "appid": _app_id(), "secret": _app_secret()},
        )
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        if int(body.get("errcode", 0)) != 0:
            raise RuntimeError(f"小程序 gettoken 失败: {body.get('errmsg')} (errcode={body.get('errcode')})")
        token = str(body.get("access_token", ""))
        ttl = int(body.get("expires_in", 7200))
        if not token:
            raise RuntimeError("小程序 gettoken 返回空 token")
        return token, ttl

    def _ensure_token_cache(self) -> CachedToken:
        current_key = (_app_id(), _app_secret())
        if self._token is None or self._token_config_key != current_key:
            self._token = CachedToken(self._fetch_token, ttl_sec=7000)
            self._token_config_key = current_key
        return self._token

    async def _on_token_invalid(self) -> None:
        if self._token is not None:
            self._token.invalidate()

    # ----------------- send_message -----------------

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        """发送订阅消息。

        contact_id: 用户的 openid
        kwargs:
          - template_id: 模板 ID（默认 self._template_id）
          - data: dict[str, str] 模板字段填充
          - page: 跳转页面
        """
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}
        if not contact_id:
            return {"success": False, "message_id": "", "error": "contact_id (openid) 不能为空"}

        template_id = str(kwargs.get("template_id") or _template_id())
        if not template_id:
            return {"success": False, "message_id": "", "error": "缺少 template_id（设置渠道 template_id 或传 template_id）"}

        # 兼容两种调用：直接传 content 走默认 "thing" 字段；或传 data 走完整模板
        data: dict[str, dict[str, str]] = kwargs.get("data") or {}
        if not data:
            data = {
                "thing1": {"value": (content or "")[:20] or "（无内容）"},
                "time2": {"value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")},
            }

        try:
            token = await self._ensure_token_cache().get()
            client = await self._get_client()
            payload = {
                "touser": contact_id,
                "template_id": template_id,
                "data": data,
                "miniprogram_state": str(kwargs.get("miniprogram_state", "formal")),
            }
            if kwargs.get("page"):
                payload["page"] = str(kwargs["page"])
            resp = await client.post(
                "/cgi-bin/message/subscribe/send",
                params={"access_token": token},
                json=payload,
            )
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            errcode = int(body.get("errcode", 0) or 0)
            if errcode != 0 and errcode != 43101:  # 43101: 用户拒绝订阅，期望值
                return {
                    "success": False,
                    "message_id": "",
                    "error": f"errcode={errcode} errmsg={body.get('errmsg')}",
                }
            return {
                "success": errcode == 0,
                "message_id": "",  # 订阅消息无 message_id
                "error": "" if errcode == 0 else f"errcode={errcode} errmsg={body.get('errmsg')}",
            }
        except Exception as exc:
            logger.warning("小程序 send_message 异常: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        """从收件箱表读取（云函数 HTTP 触发已写入）。"""
        try:
            from app.services.message_store import list_inbox
            rows: list[dict[str, Any]] = []
            for channel_type in _inbox_channel_types():
                rows.extend(list_inbox(channel_type, limit=max(int(limit), 1)))
            rows.sort(key=lambda item: str(item.get("received_at", "")), reverse=True)
            rows = rows[: int(limit)]
        except Exception as exc:
            logger.warning("读取小程序收件箱失败: %s", exc)
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
                    channel_type=str(r.get("channel_type") or self.channel_type),
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
        """小程序联系人：从收件箱聚合 openid 集合。"""
        try:
            from app.services.message_store import list_inbox
            rows: list[dict[str, Any]] = []
            for channel_type in _inbox_channel_types():
                rows.extend(list_inbox(channel_type, limit=500, include_consumed=True))
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
                "channel": str(r.get("channel_type") or self.channel_type),
            }
            if keyword and keyword.lower() not in seen[cid]["name"].lower():
                seen.pop(cid)
                continue
            if len(seen) >= int(limit):
                break
        return list(seen.values())

    # ----------------- test_connection -----------------

    async def test_connection(self) -> dict:
        if not self._is_configured():
            return {"connected": False, "message": _UNCONFIGURED_MSG}
        try:
            token, _ = await self._fetch_token()
            if token:
                return {"connected": True, "message": "小程序 access_token 拉取成功"}
            return {"connected": False, "message": "小程序 token 为空"}
        except Exception as exc:
            return {"connected": False, "message": f"小程序连接失败: {exc}"}
