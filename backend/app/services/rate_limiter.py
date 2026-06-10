"""简单的内存版 token bucket 限流器。

实现要点：
- 每个 key 维护一个令牌桶，按时间窗口补充令牌
- 线程安全（使用 threading.Lock 保护共享状态）
- 进程内有效；多进程部署需切换到 Redis 版本
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _Bucket:
    """单个 key 的令牌桶状态"""

    capacity: float  # 桶容量（最大令牌数）
    refill_rate: float  # 每秒补充的令牌数
    tokens: float  # 当前剩余令牌
    last_refill: float  # 上次补充时间戳
    lock: threading.Lock = field(default_factory=threading.Lock)


class InMemoryTokenBucketLimiter:
    """基于内存的 token bucket 限流器"""

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._global_lock = threading.Lock()

    def _get_or_create(self, key: str, capacity: float, refill_rate: float) -> _Bucket:
        bucket = self._buckets.get(key)
        if bucket is not None:
            return bucket
        with self._global_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(
                    capacity=capacity,
                    refill_rate=refill_rate,
                    tokens=capacity,
                    last_refill=time.monotonic(),
                )
                self._buckets[key] = bucket
            return bucket

    def try_acquire(
        self,
        key: str,
        *,
        capacity: float,
        refill_rate: float,
        cost: float = 1.0,
    ) -> tuple[bool, float]:
        """尝试获取一个令牌

        返回 (是否成功, 距离桶满的剩余秒数)
        """
        bucket = self._get_or_create(key, capacity, refill_rate)
        with bucket.lock:
            now = time.monotonic()
            elapsed = max(0.0, now - bucket.last_refill)
            # 补充令牌
            bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_rate)
            bucket.last_refill = now
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                # 距离桶满的剩余时间
                if bucket.refill_rate > 0:
                    retry_after = max(0.0, (bucket.capacity - bucket.tokens) / bucket.refill_rate)
                else:
                    retry_after = 0.0
                return True, retry_after
            # 令牌不足：估算需要等多久
            if bucket.refill_rate > 0:
                retry_after = max(0.0, (cost - bucket.tokens) / bucket.refill_rate)
            else:
                retry_after = 60.0
            return False, retry_after

    def reset(self, key: str) -> None:
        """重置指定 key 的桶（测试/管理用）"""
        with self._global_lock:
            self._buckets.pop(key, None)


# --- 单例：LLM 限流 ---
# 每用户每分钟最多 20 次：capacity=20, refill_rate=20/60 ≈ 0.333
_llm_limiter = InMemoryTokenBucketLimiter()
LLM_LIMITER_CAPACITY = 20
LLM_LIMITER_REFILL_PER_SEC = 20.0 / 60.0  # 每秒 1/3 个令牌


def check_llm_rate_limit(user_key: str) -> tuple[bool, float]:
    """对 LLM 端点进行限流检查

    user_key 通常为 "user:<id>" 或 "ip:<addr>"。
    返回 (是否放行, 重试等待秒数)。
    """
    return _llm_limiter.try_acquire(
        f"llm:{user_key}",
        capacity=LLM_LIMITER_CAPACITY,
        refill_rate=LLM_LIMITER_REFILL_PER_SEC,
    )


def reset_llm_rate_limit(user_key: str) -> None:
    """重置指定用户的 LLM 限流（管理用）"""
    _llm_limiter.reset(f"llm:{user_key}")


# --- 单例：登录限流 ---
# 每 IP 每 15 分钟最多 10 次尝试：capacity=10, refill_rate=10/900 ≈ 0.011
_login_limiter = InMemoryTokenBucketLimiter()
LOGIN_LIMITER_CAPACITY = 10
LOGIN_LIMITER_REFILL_PER_SEC = 10.0 / 900.0  # 每 15 分钟补充 10 个令牌


def check_login_rate_limit(ip_key: str) -> tuple[bool, float]:
    """对登录端点进行限流检查（防暴力破解）

    ip_key 通常为 "ip:<addr>"。
    返回 (是否放行, 重试等待秒数)。
    """
    return _login_limiter.try_acquire(
        f"login:{ip_key}",
        capacity=LOGIN_LIMITER_CAPACITY,
        refill_rate=LOGIN_LIMITER_REFILL_PER_SEC,
    )


def reset_login_rate_limit(ip_key: str) -> None:
    """重置指定 IP 的登录限流（测试/管理用）"""
    _login_limiter.reset(f"login:{ip_key}")


# --- 单例：注册限流 ---
# 每 IP 每小时最多 5 次注册：capacity=5, refill_rate=5/3600 ≈ 0.00139
_register_limiter = InMemoryTokenBucketLimiter()
REGISTER_LIMITER_CAPACITY = 5
REGISTER_LIMITER_REFILL_PER_SEC = 5.0 / 3600.0  # 每小时补充 5 个令牌


def check_register_rate_limit(ip_key: str) -> tuple[bool, float]:
    """对注册端点进行限流检查（防垃圾注册、DB 膨胀）

    ip_key 通常为 "ip:<addr>"。
    返回 (是否放行, 重试等待秒数)。
    """
    return _register_limiter.try_acquire(
        f"register:{ip_key}",
        capacity=REGISTER_LIMITER_CAPACITY,
        refill_rate=REGISTER_LIMITER_REFILL_PER_SEC,
    )


def reset_register_rate_limit(ip_key: str) -> None:
    """重置指定 IP 的注册限流（测试/管理用）"""
    _register_limiter.reset(f"register:{ip_key}")
