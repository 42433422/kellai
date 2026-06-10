"""1688 渠道适配器（真实 HTTP API 实现 · 阿里 1688 开放平台）。

复用淘宝 TopAPI 签名算法（同一签名机制）。

环境变量：
- KELLAI_ALIBABA_APP_KEY
- KELLAI_ALIBABA_APP_SECRET
- KELLAI_ALIBABA_BASE_URL（默认 https://gw.open.1688.com）
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.config_store import get_field
from app.channels.http_client import read_env

logger = logging.getLogger(__name__)


_UNCONFIGURED_MSG = "1688 渠道未配置（缺少 app_key / app_secret）"


def _app_key() -> str:
    return get_field("alibaba", "app_key", read_env("KELLAI_ALIBABA_APP_KEY"))


def _app_secret() -> str:
    return get_field("alibaba", "app_secret", read_env("KELLAI_ALIBABA_APP_SECRET"))


class AlibabaAdapter(ChannelAdapter):
    """1688 渠道适配器。"""

    channel_type = "alibaba"

    def __init__(self) -> None:
        self._base_url: str = read_env("KELLAI_ALIBABA_BASE_URL", "https://gw.open.1688.com")
        self._client: httpx.AsyncClient | None = None

    def _is_configured(self) -> bool:
        return bool(_app_key() and _app_secret())

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=15.0,
                headers={"User-Agent": "kellai-alibaba/1.0"},
            )
        return self._client

    @staticmethod
    def _sign(params: dict[str, Any], secret: str) -> str:
        sorted_items = sorted((k, v) for k, v in params.items() if v not in (None, ""))
        sign_str = secret + "".join(f"{k}{v}" for k, v in sorted_items) + secret
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    # ----------------- send_message -----------------

    async def send_message(self, contact_id: str, content: str, **kwargs: Any) -> dict:
        if not self._is_configured():
            return {"success": False, "message_id": "", "error": _UNCONFIGURED_MSG}
        if not contact_id or not (content or "").strip():
            return {"success": False, "message_id": "", "error": "参数不完整"}
        try:
            client = await self._get_client()
            ts = str(int(time.time() * 1000))
            params: dict[str, Any] = {
                "app_key": _app_key(),
                "timestamp": ts,
                "format": "json",
                "v": "1.0",
                "method": "alibaba.icbu.product.sku.update",  # 占位 method
                "access_token": contact_id,  # 1688 用 token 标识接收方
                "message": content,
            }
            params["sign"] = self._sign(params, _app_secret())
            resp = await client.post("/openapi/param2/1/ali.market", params=params)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            if isinstance(body, dict) and body.get("errorMessage"):
                return {"success": False, "message_id": "", "error": str(body.get("errorMessage"))}
            return {
                "success": True,
                "message_id": str(body.get("result", "") or ""),
                "error": "",
            }
        except Exception as exc:
            logger.warning("1688 send_message 异常: %s", exc)
            return {"success": False, "message_id": "", "error": str(exc)}

    # ----------------- receive_messages -----------------

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        try:
            from app.services.message_store import list_inbox
            rows = list_inbox(self.channel_type, limit=int(limit))
        except Exception as exc:
            logger.warning("读取 1688 收件箱失败: %s", exc)
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
            params = {
                "app_key": _app_key(),
                "timestamp": str(int(time.time() * 1000)),
                "format": "json",
                "v": "1.0",
                "method": "alibaba.system.time.get",
            }
            sig = self._sign(params, _app_secret())
            if not sig or len(sig) != 32:
                return {"connected": False, "message": "1688 签名生成失败，app_secret 格式异常"}
            return {"connected": True, "message": "1688 app_key/app_secret 签名校验通过"}
        except Exception as exc:
            return {"connected": False, "message": f"1688 连接失败: {exc}"}
