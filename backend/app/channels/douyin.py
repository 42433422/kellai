"""抖音企业号渠道适配器（真实 OAuth + Webhook + 私信 OpenAPI）。

参考：抖音开放平台 https://open.douyin.com
- 应用鉴权：client_key / client_secret → client_token（仅验证应用凭据）
- 企业号授权：扫码 OAuth code → 用户 access_token / refresh_token / open_id
- 发送私信：POST /enterprise/im/message/send/
- 接收私信：/api/kellai/webhook/douyin → kellai_channel_inbox

环境变量：
- KELLAI_DOUYIN_CLIENT_KEY
- KELLAI_DOUYIN_CLIENT_SECRET
- KELLAI_DOUYIN_APP_ID（兼容前端字段 app_id）
- KELLAI_DOUYIN_APP_SECRET（兼容前端字段 app_secret）
- KELLAI_DOUYIN_BASE_URL（默认 https://open.douyin.com）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.http_client import read_env
from app.services.douyin_channel import (
    DouyinChannelError,
    access_context,
    business_token_context,
    client_key,
    client_secret,
    get_authorization,
    miniapp_app_id,
    miniapp_secret,
    remote_bridge_enabled,
    remote_connection_status,
    remote_pull_inbox,
    remote_send_message,
)

logger = logging.getLogger(__name__)


_UNCONFIGURED_MSG = "抖音渠道未配置（缺少 Client Key / Client Secret）"
_UNAUTHORIZED_MSG = "抖音应用凭据已配置，但当前团队尚未扫码授权企业号"


class DouyinAdapter(ChannelAdapter):
    """抖音渠道适配器。"""

    channel_type = "douyin"

    def __init__(self) -> None:
        self._base_url: str = read_env("KELLAI_DOUYIN_BASE_URL", "https://open.douyin.com")
        self._client: httpx.AsyncClient | None = None

    def _is_configured(self) -> bool:
        return (
            remote_bridge_enabled()
            or bool(client_key() and client_secret())
            or bool(miniapp_app_id() and miniapp_secret())
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=15.0,
                headers={"User-Agent": "kellai-douyin/1.0"},
            )
        return self._client

    async def _fetch_client_token(self) -> tuple[str, int]:
        """拉取 client_token，仅用于验证开放平台应用凭据。"""
        client = await self._get_client()
        resp = await client.post(
            "/oauth/client_token/",
            json={
                "client_key": client_key(),
                "client_secret": client_secret(),
                "grant_type": "client_credential",
            },
        )
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        data = body.get("data", {}) if isinstance(body, dict) else {}
        error_code = int(data.get("error_code", 0) or 0)
        token = str(data.get("access_token", ""))
        ttl = int(data.get("expires_in", 7200))
        if resp.status_code >= 400 or error_code != 0 or not token:
            raise RuntimeError(f"抖音 client_token 拉取失败: {body}")
        return token, ttl

    # ----------------- send_message -----------------

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        """发送抖音私信。

        contact_id: 抖音用户的 open_id
        content: 文本内容
        """
        content = (content or "").strip()
        if not content:
            return {"success": False, "message_id": "", "error": "消息内容为空"}
        if not contact_id:
            return {"success": False, "message_id": "", "error": "contact_id 不能为空"}

        team_id = int(kwargs.get("team_id") or 0)
        desktop_target = self._resolve_desktop_target(
            customer_id=int(kwargs.get("customer_id") or 0),
            contact_id=contact_id,
            contact_name=str(kwargs.get("contact_name") or ""),
            team_id=team_id,
        )
        if desktop_target:
            from app.services.douyin_desktop_automation import (
                automation_enabled,
                send_message as send_desktop_message,
            )

            if automation_enabled(team_id=team_id, source=desktop_target["source"]):
                return await asyncio.to_thread(
                    send_desktop_message,
                    contact_name=desktop_target["contact_name"],
                    contact_id=contact_id,
                    content=content,
                )

        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}
        if team_id <= 0:
            return {"success": False, "message_id": "", "error": "发送抖音私信缺少当前团队上下文"}

        reply_context = self._resolve_reply_context(
            customer_id=int(kwargs.get("customer_id") or 0),
            contact_id=contact_id,
            team_id=team_id,
            supplied=kwargs.get("reply_context"),
        )
        try:
            if remote_bridge_enabled():
                return await remote_send_message(
                    team_id=team_id,
                    contact_id=contact_id,
                    content=content,
                    persona_id=str(kwargs.get("persona_id") or ""),
                    customer_id=int(kwargs.get("customer_id") or 0),
                    reply_context=reply_context,
                )
            event_app_id = str(reply_context.get("miniapp_app_id") or "").strip()
            if event_app_id and event_app_id == miniapp_app_id():
                return await self._send_miniapp_private_message(
                    team_id=team_id,
                    contact_id=contact_id,
                    content=content,
                    reply_context=reply_context,
                )
            if miniapp_app_id() and int(kwargs.get("customer_id") or 0) > 0 and not event_app_id:
                return {
                    "success": False,
                    "message_id": "",
                    "error": "该客户还没有可回复的抖音私信上下文，请先让客户向已绑定抖音号发送一条新私信",
                }
            client = await self._get_client()
            auth = await access_context(team_id)
            payload = {
                "message_type": "text",
                "to_user_id": contact_id,
                "persona_id": str(kwargs.get("persona_id") or ""),
                "content": json.dumps(
                    {"text": content},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
            resp = await client.post(
                "/enterprise/im/message/send/",
                params={
                    "access_token": auth["access_token"],
                    "open_id": auth["open_id"],
                },
                json=payload,
            )
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            data = body.get("data", {}) if isinstance(body, dict) else {}
            extra = body.get("extra", {}) if isinstance(body, dict) else {}
            error_code = int(
                data.get("error_code")
                or extra.get("error_code")
                or body.get("errcode", 0)
                or 0
            )
            if resp.status_code >= 400 or error_code != 0:
                description = (
                    data.get("description")
                    or extra.get("description")
                    or body.get("errmsg")
                    or ""
                )
                return {
                    "success": False,
                    "message_id": "",
                    "error": f"error_code={error_code} description={description}",
                }
            return {
                "success": True,
                "message_id": str(data.get("server_msg_id") or data.get("message_id") or ""),
                "error": "",
                "open_id": str(auth["open_id"]),
            }
        except DouyinChannelError as exc:
            return {"success": False, "message_id": "", "error": str(exc)}
        except Exception as exc:
            logger.warning("抖音 send_message 异常: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    @staticmethod
    def _resolve_desktop_target(
        *,
        customer_id: int,
        contact_id: str,
        contact_name: str,
        team_id: int,
    ) -> dict[str, str] | None:
        """解析网页收信客户的桌面端昵称，避免拿 open_id 去搜索。"""
        resolved_name = str(contact_name or "").strip()
        source = ""
        if customer_id > 0:
            try:
                from app.services.message_store import get_messages

                for message in get_messages(customer_id, "douyin", limit=100):
                    if str(message.contact_id or "") != str(contact_id or ""):
                        continue
                    metadata = message.metadata if isinstance(message.metadata, dict) else {}
                    message_team_id = int(metadata.get("team_id") or 0)
                    if team_id > 0 and message_team_id not in {0, int(team_id)}:
                        continue
                    resolved_name = resolved_name or str(message.contact_name or "").strip()
                    if str(metadata.get("source") or "") == "douyin_web_portal":
                        source = "douyin_web_portal"
                        break
            except Exception:
                logger.debug("解析抖音桌面联系人失败", exc_info=True)

        if not source and team_id > 0:
            try:
                from app.services.douyin_web_portal import list_contacts

                for row in list_contacts(team_id, limit=1000):
                    if str(row.get("contact_id") or "") != str(contact_id or ""):
                        continue
                    resolved_name = resolved_name or str(row.get("contact_name") or "").strip()
                    source = "douyin_web_portal"
                    break
            except Exception:
                logger.debug("从抖音网页联系人表解析昵称失败", exc_info=True)

        explicitly_enabled = os.environ.get(
            "KELLAI_DOUYIN_DESKTOP_AUTOMATION",
            "",
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not source and explicitly_enabled:
            source = "manual"
        if not resolved_name or not source:
            return None
        return {"contact_name": resolved_name, "source": source}

    @staticmethod
    def _resolve_reply_context(
        *,
        customer_id: int,
        contact_id: str,
        team_id: int,
        supplied: Any,
    ) -> dict[str, Any]:
        raw = dict(supplied) if isinstance(supplied, dict) else {}
        if not raw and customer_id > 0:
            try:
                from app.services.message_store import get_messages

                for message in get_messages(customer_id, "douyin", limit=50):
                    metadata = message.metadata if isinstance(message.metadata, dict) else {}
                    if str(message.contact_id or "") != str(contact_id or ""):
                        continue
                    if str(message.direction or "").lower() != "inbound":
                        continue
                    if int(metadata.get("team_id") or 0) not in {0, int(team_id)}:
                        continue
                    if metadata.get("server_message_id") and metadata.get("conversation_id"):
                        raw = dict(metadata)
                        break
            except Exception:
                logger.warning(
                    "读取抖音私信回复上下文失败: customer_id=%s",
                    customer_id,
                    exc_info=True,
                )
        allowed = {
            "event",
            "team_id",
            "owner_open_id",
            "miniapp_app_id",
            "conversation_id",
            "server_message_id",
            "message_index",
        }
        return {key: value for key, value in raw.items() if key in allowed and value not in {None, ""}}

    async def _send_miniapp_private_message(
        self,
        *,
        team_id: int,
        contact_id: str,
        content: str,
        reply_context: dict[str, Any],
    ) -> dict[str, Any]:
        owner_open_id = str(reply_context.get("owner_open_id") or "").strip()
        message_id = str(reply_context.get("server_message_id") or "").strip()
        conversation_id = str(reply_context.get("conversation_id") or "").strip()
        if not owner_open_id or owner_open_id == miniapp_app_id():
            return {
                "success": False,
                "message_id": "",
                "error": "抖音私信事件缺少经营抖音号 open_id，请确认已订阅 im_receive_msg / im_send_msg",
            }
        if not message_id or not conversation_id:
            return {
                "success": False,
                "message_id": "",
                "error": "抖音私信事件缺少消息 ID 或会话 ID，暂时无法回复",
            }

        token_context = await business_token_context(
            team_id=team_id,
            owner_open_id=owner_open_id,
            scope="im.direct_message",
        )
        client = await self._get_client()
        response = await client.post(
            "/im/send/msg/",
            params={"open_id": owner_open_id},
            headers={
                "access-token": str(token_context["business_token"]),
                "Content-Type": "application/json",
            },
            json={
                "content": {
                    "msg_type": 1,
                    "text": {"text": content},
                },
                "to_user_id": contact_id,
                "msg_id": message_id,
                "conversation_id": conversation_id,
                "scene": "im_reply_msg",
            },
        )
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}
        data = body.get("data", {}) if isinstance(body, dict) else {}
        extra = body.get("extra", {}) if isinstance(body, dict) else {}
        error_code = int(
            data.get("error_code")
            or extra.get("error_code")
            or body.get("err_no", 0)
            or body.get("error_code", 0)
            or 0
        )
        if response.status_code >= 400 or error_code != 0:
            description = str(
                data.get("description")
                or extra.get("description")
                or body.get("err_msg")
                or body.get("message")
                or ""
            )
            return {
                "success": False,
                "message_id": "",
                "error": f"error_code={error_code} description={description}",
            }
        sent_id = str(
            body.get("msg_id")
            or data.get("msg_id")
            or data.get("server_msg_id")
            or ""
        )
        return {
            "success": True,
            "message_id": sent_id,
            "error": "",
            "open_id": owner_open_id,
            "source": "miniapp_private_message",
            "scene": "im_reply_msg",
        }

    # ----------------- receive_messages -----------------

    async def receive_messages(
        self,
        since: str = "",
        limit: int = 50,
        **kwargs: Any,
    ) -> list[UnifiedMessage]:
        """从收件箱表读取待消费消息（webhook 已写入）。"""
        try:
            team_id = int(kwargs.get("team_id") or 0)
            if remote_bridge_enabled():
                if team_id <= 0:
                    return []
                rows = await remote_pull_inbox(team_id, limit=int(limit))
            else:
                from app.services.message_store import list_inbox

                rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取抖音收件箱失败: %s", exc)
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
        """抖音侧联系人列表 — 简化返回最近互动 open_id 集合。

        真实实现需要 user/info 接口（需用户授权）。此处返回空（依赖 webhook 累积）。
        """
        # 实际生产：从 inbox 聚合 contact_id + name
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
            if keyword and keyword.lower() not in seen[cid]["name"].lower():
                seen.pop(cid)
                continue
            if len(seen) >= int(limit):
                break
        return list(seen.values())

    # ----------------- test_connection -----------------

    async def test_connection(self, **kwargs: Any) -> dict:
        if not self._is_configured():
            return {"connected": False, "message": _UNCONFIGURED_MSG}
        team_id = int(kwargs.get("team_id") or 0)
        try:
            if remote_bridge_enabled():
                if team_id <= 0:
                    return {"connected": False, "message": "抖音远端服务已配置，但缺少当前团队上下文"}
                return await remote_connection_status(team_id)
            token, _ = await self._fetch_client_token()
            if not token:
                return {"connected": False, "message": "抖音 client_token 为空"}
            if team_id <= 0:
                return {
                    "connected": False,
                    "credentials_valid": True,
                    "message": _UNAUTHORIZED_MSG,
                }
            auth = get_authorization(team_id, include_tokens=False)
            if auth is None:
                return {
                    "connected": False,
                    "credentials_valid": True,
                    "message": _UNAUTHORIZED_MSG,
                }
            scope = {item.strip() for item in str(auth.get("scope") or "").split(",") if item.strip()}
            if "im.direct_message" not in scope:
                return {
                    "connected": False,
                    "credentials_valid": True,
                    "message": "抖音账号已完成基础授权；开放平台尚未授予 im.direct_message 私信权限，私信收发暂不可用",
                }
            await access_context(team_id)
            account = str(auth.get("nickname") or auth.get("open_id") or "企业号")
            return {"connected": True, "message": f"抖音企业号已授权：{account}"}
        except Exception as exc:
            return {"connected": False, "message": f"抖音连接失败: {exc}"}
