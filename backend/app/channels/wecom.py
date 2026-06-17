"""企业微信渠道适配器（真实 HTTP API 实现）。

支持两种发送方式：
- 群机器人 Webhook（最简）：配置 bot_webhook，无需 access_token
- 应用消息：配置 corp_id + secret + agent_id

配置来源：config_store（前端保存）优先，环境变量兜底。

接收：
- 主动轮询：读取 kellai_channel_inbox 表（webhook 接收方写入）
- 回调路由：/api/kellai/webhook/wework
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.http_client import BaseChannelClient, CachedToken, read_env

logger = logging.getLogger(__name__)

_UNCONFIGURED_MSG = "企业微信渠道未配置（缺少 corp_id/secret/agent_id 或 bot_webhook）"


def _cfg(field: str, default: str = "") -> str:
    """从 config_store 读取配置，环境变量兜底。"""
    from app.channels.config_store import get_field
    return get_field("wework", field, default=default) or read_env(f"KELLAI_WECOM_{field.upper()}", default=default)


def _inbox_channel_types() -> list[str]:
    """企微历史上同时出现过 wework/wecom，收件箱读取要兼容。"""
    return ["wework", "wecom"]


class _WeComClient(BaseChannelClient):
    """企业微信 HTTP 客户端。"""

    _base_url = "https://qyapi.weixin.qq.com"

    def __init__(self, corp_id: str, corp_secret: str) -> None:
        super().__init__()
        self._corp_id = corp_id
        self._corp_secret = corp_secret
        self._token: CachedToken | None = None

    def ensure_token(self) -> CachedToken:
        if self._token is None:
            if not self._corp_id or not self._corp_secret:
                raise RuntimeError(_UNCONFIGURED_MSG)
            self._token = CachedToken(
                lambda: self._fetch_token(self._corp_id, self._corp_secret),
                ttl_sec=7000,
            )
        return self._token

    async def _fetch_token(self, corp_id: str, corp_secret: str) -> tuple[str, int]:
        body = await self.get_json(
            "/cgi-bin/gettoken",
            params={"corpid": corp_id, "corpsecret": corp_secret},
        )
        if int(body.get("errcode", 0)) != 0:
            raise RuntimeError(
                f"企微 gettoken 失败: errcode={body.get('errcode')} errmsg={body.get('errmsg')}"
            )
        token = str(body.get("access_token", ""))
        ttl = int(body.get("expires_in", 7200))
        if not token:
            raise RuntimeError("企微 gettoken 返回空 token")
        return token, ttl

    async def _auth_headers(self) -> dict[str, str]:
        try:
            await self.ensure_token().get()
        except Exception:
            pass
        return {}

    async def _on_token_invalid(self) -> None:
        if self._token is not None:
            self._token.invalidate()

    async def fetch_token(self) -> str:
        return await self.ensure_token().get()

    async def post_with_token(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """所有需要 token 的接口走这个。"""
        token = await self.ensure_token().get()
        return await self.post_json(path, params={"access_token": token}, json=payload)


class WeComAdapter(ChannelAdapter):
    """企业微信渠道适配器。"""

    channel_type = "wework"

    def __init__(self) -> None:
        self._client: _WeComClient | None = None

    def _corp_id(self) -> str:
        return _cfg("corp_id")

    def _corp_secret(self) -> str:
        return _cfg("secret")

    def _agent_id(self) -> str:
        return _cfg("agent_id")

    def _bot_webhook(self) -> str:
        return _cfg("bot_webhook")

    def _is_configured(self) -> bool:
        """是否已配置（任一方式）。"""
        if self._bot_webhook():
            return True
        if self._corp_id() and self._corp_secret() and self._agent_id():
            return True
        return False

    async def _get_client(self) -> _WeComClient:
        if self._client is None:
            self._client = _WeComClient(self._corp_id(), self._corp_secret())
        return self._client

    def _refresh_client(self) -> None:
        """配置变更后刷新客户端。"""
        self._client = None

    # ----------------- send_message -----------------

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        """发送企微消息。

        contact_id:
        - 以 "@chat" 开头：视为群机器人目标
        - 否则：当作"用户/部门 id"通过应用消息发送（text 消息）
        """
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}

        content = (content or "").strip()
        if not content:
            return {"success": False, "message_id": "", "error": "消息内容为空"}
        if not contact_id:
            return {"success": False, "message_id": "", "error": "contact_id 不能为空"}

        try:
            if contact_id.startswith("@chat"):
                return await self._send_via_bot(content, kwargs.get("mentioned_list", []))
            return await self._send_via_app(contact_id, content, kwargs)
        except Exception as exc:
            logger.warning("企微 send_message 失败: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    async def _send_via_bot(self, content: str, mentioned: list[str]) -> dict:
        """群机器人 Webhook 模式（markdown 消息）。"""
        webhook = self._bot_webhook()
        if not webhook:
            return {"success": False, "message_id": "", "error": "未配置 bot_webhook"}
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(
                webhook,
                json={
                    "msgtype": "markdown",
                    "markdown": {"content": content},
                    "mentioned_list": list(mentioned or []),
                },
            )
        body = {}
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        if resp.status_code >= 400 or int(body.get("errcode", 0)) != 0:
            return {
                "success": False,
                "message_id": "",
                "error": f"企微机器人返回错误: HTTP {resp.status_code} body={body}",
            }
        return {
            "success": True,
            "message_id": str(body.get("msgid", "")),
            "error": "",
        }

    async def _send_via_app(self, user_id: str, content: str, kwargs: dict) -> dict:
        """应用消息模式：向 user_id 发送 text。"""
        corp_id = self._corp_id()
        corp_secret = self._corp_secret()
        agent_id = self._agent_id()
        if not (corp_id and corp_secret and agent_id):
            return {"success": False, "message_id": "", "error": "未配置 corp_id/secret/agent_id"}
        # 每次发送时用最新配置创建 client（配置可能已变更）
        client = _WeComClient(corp_id, corp_secret)
        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": int(agent_id),
            "text": {"content": content},
            "safe": 0,
        }
        body = await client.post_with_token("/cgi-bin/message/send", payload)
        if int(body.get("errcode", 0)) != 0:
            return {
                "success": False,
                "message_id": "",
                "error": f"errcode={body.get('errcode')} errmsg={body.get('errmsg')}",
            }
        return {
            "success": True,
            "message_id": str(body.get("msgid", "")),
            "error": "",
        }

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        """从收件箱表读取待消费消息（webhook 已写入）。"""
        try:
            from app.services.message_store import list_inbox
            rows: list[dict[str, Any]] = []
            for channel_type in _inbox_channel_types():
                rows.extend(list_inbox(channel_type, limit=max(int(limit), 1)))
            rows.sort(key=lambda item: str(item.get("received_at", "")), reverse=True)
            rows = rows[: int(limit)]
        except Exception as exc:
            logger.warning("读取企微收件箱失败: %s", exc)
            return []
        msgs: list[UnifiedMessage] = []
        for r in rows:
            created_at = str(r.get("received_at", ""))
            if since and created_at and created_at <= since:
                continue
            msgs.append(
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
        return msgs

    # ----------------- get_contacts -----------------

    async def get_contacts(self, keyword: str = "", limit: int = 80) -> list[dict]:
        """获取部门成员列表（简化为通讯录同步）。

        注意：完整通讯录 API 需要"客户联系"或"通讯录同步"权限。
        """
        corp_id = self._corp_id()
        corp_secret = self._corp_secret()
        if not (corp_id and corp_secret):
            return self._contacts_from_inbox(keyword=keyword, limit=limit)
        try:
            client = _WeComClient(corp_id, corp_secret)
            token = await client.fetch_token()
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(
                    "https://qyapi.weixin.qq.com/cgi-bin/user/simplelist",
                    params={"access_token": token, "department_id": 1, "fetch_child": 1},
                )
            body = resp.json()
            if int(body.get("errcode", 0)) != 0:
                logger.warning("企微通讯录拉取失败: %s", body.get("errmsg"))
                return []
            users = body.get("userlist", []) or []
            if keyword:
                kw = keyword.lower()
                users = [u for u in users if kw in (u.get("name", "")).lower()]
            users = users[: int(limit)]
            return [
                {
                    "id": str(u.get("userid", "")),
                    "name": str(u.get("name", "")),
                    "department": u.get("department", []),
                    "position": str(u.get("position", "")),
                }
                for u in users
            ]
        except Exception as exc:
            logger.warning("企微 get_contacts 异常: %s", exc)
            return self._contacts_from_inbox(keyword=keyword, limit=limit)

    def _contacts_from_inbox(self, keyword: str = "", limit: int = 80) -> list[dict]:
        """未配置通讯录权限时，从 webhook/收件箱沉淀的联系人兜底。"""
        try:
            from app.services.message_store import list_inbox
            rows: list[dict[str, Any]] = []
            for channel_type in _inbox_channel_types():
                rows.extend(list_inbox(channel_type, limit=500, include_consumed=True))
            rows.sort(key=lambda item: str(item.get("received_at", "")), reverse=True)
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
            seen[cid] = {
                "id": cid,
                "name": name,
                "channel": str(row.get("channel_type") or self.channel_type),
            }
            if len(seen) >= int(limit):
                break
        return list(seen.values())

    # ----------------- test_connection -----------------

    async def test_connection(self) -> dict:
        if not self._is_configured():
            return {"connected": False, "message": _UNCONFIGURED_MSG}

        if self._bot_webhook():
            return {
                "connected": True,
                "message": "企微群机器人 Webhook 已配置（无需 access_token）",
            }
        try:
            corp_id = self._corp_id()
            corp_secret = self._corp_secret()
            client = _WeComClient(corp_id, corp_secret)
            token = await client.fetch_token()
            if token:
                return {"connected": True, "message": "企微应用鉴权通过"}
            return {"connected": False, "message": "企微 token 为空"}
        except Exception as exc:
            return {"connected": False, "message": f"企微连接失败: {exc}"}
