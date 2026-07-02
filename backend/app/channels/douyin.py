"""抖音渠道适配器（真实 HTTP API 实现）。

参考：抖音开放平台 https://open.douyin.com
- 鉴权：client_key / client_secret → access_token（OAuth2 client_credentials 风格）
- 发送私信：通过 /im/message/send 或对应业务接口
- 接收：通过 webhook 回调 → 写入 kellai_channel_inbox，本接口消费

环境变量：
- KELLAI_DOUYIN_CLIENT_KEY
- KELLAI_DOUYIN_CLIENT_SECRET
- KELLAI_DOUYIN_APP_ID（兼容前端字段 app_id）
- KELLAI_DOUYIN_APP_SECRET（兼容前端字段 app_secret）
- KELLAI_DOUYIN_BASE_URL（默认 https://open.douyin.com）
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.config_store import get_field
from app.channels.http_client import CachedToken, read_env

logger = logging.getLogger(__name__)


_UNCONFIGURED_MSG = "抖音渠道未配置（缺少 KELLAI_DOUYIN_CLIENT_KEY/SECRET）"


def _client_key() -> str:
    return (
        get_field("douyin", "client_key")
        or get_field("douyin", "app_id")
        or read_env("KELLAI_DOUYIN_CLIENT_KEY")
        or read_env("KELLAI_DOUYIN_APP_ID")
    )


def _client_secret() -> str:
    return (
        get_field("douyin", "client_secret")
        or get_field("douyin", "app_secret")
        or read_env("KELLAI_DOUYIN_CLIENT_SECRET")
        or read_env("KELLAI_DOUYIN_APP_SECRET")
    )


class DouyinAdapter(ChannelAdapter):
    """抖音渠道适配器。"""

    channel_type = "douyin"

    def __init__(self) -> None:
        self._base_url: str = read_env("KELLAI_DOUYIN_BASE_URL", "https://open.douyin.com")
        self._client: httpx.AsyncClient | None = None
        self._token: CachedToken | None = None
        self._token_config_key: tuple[str, str] | None = None

    def _is_configured(self) -> bool:
        return bool(_client_key() and _client_secret())

    def _ensure_token_cache(self) -> CachedToken:
        current_key = (_client_key(), _client_secret())
        if self._token is None or self._token_config_key != current_key:
            self._token = CachedToken(self._fetch_token, ttl_sec=7000)
            self._token_config_key = current_key
        return self._token

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=15.0,
                headers={"User-Agent": "kellai-douyin/1.0"},
            )
        return self._client

    async def _fetch_token(self) -> tuple[str, int]:
        """拉取 client_credentials token。"""
        client = await self._get_client()
        resp = await client.post(
            "/oauth/client_token/",
            json={
                "client_key": _client_key(),
                "client_secret": _client_secret(),
                "grant_type": "client_credentials",
            },
        )
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text}
        data = body.get("data", {}) if isinstance(body, dict) else {}
        token = str(data.get("access_token", ""))
        ttl = int(data.get("expires_in", 7200))
        if not token:
            raise RuntimeError(f"抖音 client_token 拉取失败: {body}")
        return token, ttl

    async def _auth_headers(self) -> dict[str, str]:
        if not self._is_configured():
            return {}
        token = await self._ensure_token_cache().get()
        return {"access-token": token}

    async def _on_token_invalid(self) -> None:
        if self._token is not None:
            self._token.invalidate()

    # ----------------- send_message -----------------

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        """发送抖音私信。

        contact_id: 抖音用户的 open_id
        content: 文本内容
        """
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}
        content = (content or "").strip()
        if not content:
            return {"success": False, "message_id": "", "error": "消息内容为空"}
        if not contact_id:
            return {"success": False, "message_id": "", "error": "contact_id 不能为空"}

        try:
            client = await self._get_client()
            token = await self._ensure_token_cache().get()
            payload = {
                "to_user_id": contact_id,
                "message_type": "text",
                "content": {"text": content},
            }
            resp = await client.post(
                "/im/message/send/",
                params={"access_token": token},
                json=payload,
            )
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            # 抖音返回 errcode / errmsg / data
            errcode = int(body.get("errcode", 0) or 0)
            if errcode != 0:
                return {
                    "success": False,
                    "message_id": "",
                    "error": f"errcode={errcode} errmsg={body.get('errmsg', '')}",
                }
            data = body.get("data", {}) if isinstance(body, dict) else {}
            return {
                "success": True,
                "message_id": str(data.get("message_id", "")),
                "error": "",
            }
        except Exception as exc:
            logger.warning("抖音 send_message 异常: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        """从收件箱表读取待消费消息（webhook 已写入）。"""
        try:
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

    async def test_connection(self) -> dict:
        if not self._is_configured():
            return {"connected": False, "message": _UNCONFIGURED_MSG}
        try:
            token, _ = await self._fetch_token()
            if token:
                return {"connected": True, "message": "抖音 client_token 拉取成功"}
            return {"connected": False, "message": "抖音 token 为空"}
        except Exception as exc:
            return {"connected": False, "message": f"抖音连接失败: {exc}"}
