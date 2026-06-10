"""渠道 HTTP 客户端基类：统一鉴权 / 重试 / 超时 / 限流。

为各渠道适配器（企微 / 微信 / 抖音 / 短信 / 小程序）提供：
- 异步 HTTP 调用（httpx.AsyncClient）
- access_token 缓存（线程安全，自动过期刷新）
- 指数退避重试
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

    def __init__(self, message: str, *, status_code: int = 0, errcode: int = 0, errmsg: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.errcode = errcode
        self.errmsg = errmsg


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
        """发起 HTTP 请求，统一处理鉴权/重试/限流。"""
        await self._bucket.acquire()
        merged: dict[str, str] = dict(await self._auth_headers())
        if headers:
            merged.update({str(k): str(v) for k, v in headers.items()})

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                client = await self._get_client()
                resp = await client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    data=data,
                    headers=merged,
                )
                if resp.status_code >= 500 and attempt < self._max_retries:
                    logger.warning(
                        "%s %s -> %s, retry %d/%d",
                        method, path, resp.status_code, attempt + 1, self._max_retries,
                    )
                    await asyncio.sleep(0.3 * (2 ** attempt))
                    continue

                if expect_json:
                    try:
                        body = resp.json()
                    except Exception:
                        body = {"raw": resp.text}

                    # 微信 / 企微风格 errcode 判断
                    errcode = 0
                    if isinstance(body, dict):
                        errcode = int(body.get("errcode", 0) or 0)
                    if errcode and errcode != 0:
                        # 40001/42001: access_token 失效 → 重试一次（让 token 缓存失效后刷新）
                        if errcode in (40001, 42001, 40014) and attempt < self._max_retries:
                            await self._on_token_invalid()
                            continue
                        raise ChannelHTTPError(
                            f"{method} {path} errcode={errcode}: {body.get('errmsg', '')}",
                            status_code=resp.status_code,
                            errcode=errcode,
                            errmsg=str(body.get("errmsg", "")),
                        )
                    if resp.status_code >= 400:
                        raise ChannelHTTPError(
                            f"{method} {path} HTTP {resp.status_code}: {body}",
                            status_code=resp.status_code,
                        )
                    return body
                else:
                    if resp.status_code >= 400:
                        raise ChannelHTTPError(
                            f"{method} {path} HTTP {resp.status_code}: {resp.text[:200]}",
                            status_code=resp.status_code,
                        )
                    return resp.text
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    logger.warning("%s %s net error: %s, retry %d", method, path, exc, attempt + 1)
                    await asyncio.sleep(0.3 * (2 ** attempt))
                    continue
                raise ChannelHTTPError(f"{method} {path} 网络异常: {exc}") from exc
        if last_exc:
            raise ChannelHTTPError(f"{method} {path} 重试耗尽: {last_exc}") from last_exc
        raise ChannelHTTPError(f"{method} {path} 未知错误")  # pragma: no cover

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
