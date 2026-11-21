"""渠道 HTTP 客户端基类：统一鉴权 / 重试 / 超时 / 限流。

为各渠道适配器（企微 / 微信 / 抖音 / 短信 / 小程序）提供：
- 异步 HTTP 调用（httpx.AsyncClient）
- access_token 缓存（线程安全，自动过期刷新）
- 安全只读请求指数退避重试；发送请求不盲目重试
- 统一错误码 → 异常
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Mapping, Optional

import httpx

logger = logging.getLogger(__name__)


class ChannelHTTPError(RuntimeError):
    """渠道 HTTP 调用错误。"""

    def __init__(self, message: str, *, status_code: int = 0, errcode: int = 0, errmsg: str = "",
                 delivery_state: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.errcode = errcode
        self.errmsg = errmsg
        self.delivery_state = delivery_state or ("unknown" if status_code == 0 or status_code >= 500 else "failed")


def checked_json(response: httpx.Response) -> dict[str, Any]:
    """Reject HTTP errors and malformed responses before interpreting provider fields."""
    if not 200 <= response.status_code < 300:
        raise ChannelHTTPError(f"渠道 HTTP {response.status_code}", status_code=response.status_code)
    try:
        body = response.json()
    except (ValueError, TypeError) as exc:
        raise ChannelHTTPError("渠道响应不是有效 JSON，发送结果未知", delivery_state="unknown") from exc
    if not isinstance(body, dict):
        raise ChannelHTTPError("渠道响应格式错误，发送结果未知", delivery_state="unknown")
    return body


def send_error(error: Exception | str, *, definitely_not_sent: bool = False) -> dict[str, Any]:
    """Do not turn a transport failure into permission to automatically send again."""
    if isinstance(error, ChannelHTTPError):
        definitely_not_sent = error.delivery_state == "failed"
    message = f"渠道网络异常 ({type(error).__name__})" if isinstance(error, httpx.TransportError) else str(error)
    return {"success": False, "message_id": "", "error": message,
            "delivery_state": "failed" if definitely_not_sent else "unknown",
            "definitely_not_sent": definitely_not_sent, "retryable": False}


class TokenBucket:
    """进程内令牌桶限流（异步安全）。"""

    def __init__(self, capacity: int = 20, refill_per_sec: float = 1.0) -> None:
        self._capacity = capacity
        self._refill = refill_per_sec
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, n: int = 1) -> float:
        """消耗 n 个令牌；不足则等待。返回等待的秒数。"""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._refill)
                if self._tokens >= n:
                    self._tokens -= n
                    return 0.0
                need = n - self._tokens
                wait = need / self._refill if self._refill > 0 else 1.0
                await asyncio.sleep(wait)
                # 循环再判断一次（醒来后可能已攒够）


class CachedToken:
    """带过期时间的 access_token 缓存（异步安全）。"""

    def __init__(self, refresh_fn, *, ttl_sec: int = 7000):
        # type: (refresh_fn: Callable[[], Awaitable[Tuple[str, int]]], ttl_sec: int) -> None
        self._refresh_fn = refresh_fn
        self._ttl = ttl_sec
        self._value: str = ""
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> str:
        if self._value and time.time() < self._expires_at - 30:
            return self._value
        async with self._lock:
            if self._value and time.time() < self._expires_at - 30:
                return self._value
            value, ttl = await self._refresh_fn()
            self._value = value
            self._expires_at = time.time() + (ttl or self._ttl)
            logger.debug("刷新 access_token: ttl=%ds", self._ttl)
            return self._value

    def invalidate(self) -> None:
        self._value = ""
        self._expires_at = 0.0


class BaseChannelClient:
    """渠道 HTTP 客户端基类。

    子类可重写：
    - _base_url: API 根地址
    - _default_headers: 公共头
    - _auth_headers(): 每次请求前动态生成（如带 token）
    """

    _base_url: str = ""
    _timeout_sec: float = 15.0
    _max_retries: int = 2

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._bucket = TokenBucket(capacity=30, refill_per_sec=5.0)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_sec,
                headers=self._default_headers,
            )
        return self._client

    @property
    def _default_headers(self) -> dict[str, str]:
        return {"User-Agent": "kellai-channel/1.0", "Accept": "application/json"}

    async def _auth_headers(self) -> dict[str, str]:
        return {}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        expect_json: bool = True,
    ) -> Any:
        """Retry only safe reads; a timed-out mutation may already have been sent."""
        await self._bucket.acquire()
        retries = self._max_retries if method.upper() in {"GET", "HEAD", "OPTIONS"} else 0
        for attempt in range(retries + 1):
            try:
                merged = dict(await self._auth_headers())
                merged.update({str(k): str(v) for k, v in (headers or {}).items()})
                client = await self._get_client()
                resp = await client.request(method, path, params=params, json=json, data=data, headers=merged)
                if resp.status_code >= 500 and attempt < retries:
                    await asyncio.sleep(0.3 * (2 ** attempt))
                    continue
                if not expect_json:
                    if not 200 <= resp.status_code < 300:
                        raise ChannelHTTPError(f"HTTP {resp.status_code}", status_code=resp.status_code)
                    return resp.text
                body = checked_json(resp)
                errcode = int(body.get("errcode", 0) or 0)
                if errcode:
                    if errcode in (40001, 42001, 40014):
                        # Clear for the next request. Retrying this request would reuse
                        # the stale token already embedded in params.
                        await self._on_token_invalid()
                    raise ChannelHTTPError(
                        f"渠道拒绝请求: errcode={errcode} {body.get('errmsg', '')}",
                        status_code=resp.status_code, errcode=errcode,
                        errmsg=str(body.get("errmsg", "")), delivery_state="failed",
                    )
                return body
            except httpx.TransportError as exc:
                if attempt < retries:
                    await asyncio.sleep(0.3 * (2 ** attempt))
                    continue
                raise ChannelHTTPError(f"渠道网络异常 ({type(exc).__name__})", delivery_state="unknown") from exc
        raise ChannelHTTPError("渠道请求未完成", delivery_state="unknown")  # pragma: no cover

    async def _on_token_invalid(self) -> None:
        """token 失效时的回调（子类可重写以清缓存）。"""
        return None

    # ---------- 便捷方法 ----------
    async def get_json(self, path: str, **kwargs: Any) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post_json(self, path: str, **kwargs: Any) -> Any:
        return await self.request("POST", path, **kwargs)


# ---------------------------------------------------------------------------
# 渠道配置解析工具
# ---------------------------------------------------------------------------


def read_env(name: str, default: str = "") -> str:
    """读取环境变量，trim 空白。"""
    return (os.environ.get(name) or default).strip()


def env_present(name: str) -> bool:
    """环境变量是否存在且非空。"""
    return bool(read_env(name))
