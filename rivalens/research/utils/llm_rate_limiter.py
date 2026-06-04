"""
Redis-backed token-bucket rate limiter for LLM API calls.

Prevents concurrent deep-research tasks from exhausting provider quotas.
Configured via environment variables:

    RIVALENS_LLM_RPM_LIMIT          Global requests-per-minute (default: 0 = off)
    RIVALENS_LLM_RPM_LIMIT_OPENAI   Per-provider override (e.g. 500)
    RIVALENS_LLM_RPM_LIMIT_ANTHROPIC
    ...

Each provider gets its own bucket.  The Lua script guarantees atomic
check-and-consume so multiple workers / processes share a single limit.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

DEFAULT_REDIS_URL = "redis://:123456@localhost:6380/0"

# ── Lua: atomic token-bucket consume ──────────────────────────────

_LUA_TOKEN_BUCKET = """
-- KEYS[1]: bucket key
-- ARGV[1]: capacity (max burst)
-- ARGV[2]: rate (tokens per second)
-- ARGV[3]: requested (tokens to consume, default 1)
-- Returns: {allowed, tokens_left, wait_ms}

local key       = KEYS[1]
local capacity  = tonumber(ARGV[1])
local rate      = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])

local now_arr  = redis.call('TIME')
local now_ms   = now_arr[1] * 1000 + math.floor(now_arr[2] / 1000)

local bucket     = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens     = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now_ms)
    redis.call('EXPIRE', key, 86400)
    return {1, tokens, 0}
end

local elapsed = (now_ms - last_refill) / 1000.0
local refill  = math.floor(elapsed * rate)
if refill > 0 then
    tokens     = math.min(capacity, tokens + refill)
    last_refill = now_ms
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    redis.call('EXPIRE', key, 86400)
    return {1, tokens, 0}
end

local wait_ms = math.ceil((requested - tokens) / rate * 1000)
return {0, tokens, wait_ms}
"""


class LLMRateLimiter:
    """Singleton Redis token-bucket rate limiter for LLM API calls."""

    _instance: ClassVar[LLMRateLimiter | None] = None

    def __new__(cls) -> LLMRateLimiter:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._redis: Any = None
        self._redis_init_attempted = False
        self._script: Any = None
        self._lock = asyncio.Lock()

    # ── public ─────────────────────────────────────────────────

    def configure(
        self,
        *,
        default_rpm: int | None = None,
        provider_rpm: dict[str, int] | None = None,
    ) -> None:
        """Override rate limits at runtime."""
        if default_rpm is not None:
            self._default_rpm = default_rpm
        if provider_rpm is not None:
            self._provider_rpm.update(provider_rpm)

    async def acquire(
        self,
        provider: str,
        *,
        model: str | None = None,
        timeout: float = 30.0,
    ) -> bool:
        """Wait until a token is available, then consume one.

        Returns ``True`` when the token was acquired, ``False`` on timeout.
        """
        rpm = self._resolve_rpm(provider, model)
        if rpm <= 0:
            return True  # rate limiting disabled for this provider

        r = self._get_redis()
        if r is None:
            return True  # Redis unavailable — allow through

        capacity = max(rpm, 10)      # burst = max of rpm or 10
        rate = rpm / 60.0             # tokens per second

        deadline = time.monotonic() + timeout

        while True:
            try:
                allowed, _tokens_left, wait_ms = self._script(
                    keys=[f"llm:rate_limit:{provider}"],
                    args=[str(capacity), str(rate), "1"],
                )
            except Exception:
                logger.warning(
                    "Rate-limit bucket read failed for %s, allowing through",
                    provider,
                )
                return True

            if allowed == 1:
                return True

            wait_s = max(wait_ms / 1000.0, 0.05)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "LLM rate-limit timeout for %s after %.1fs",
                    provider,
                    timeout,
                )
                return False

            await asyncio.sleep(min(wait_s, remaining))

    # ── internal ───────────────────────────────────────────────

    def _resolve_rpm(self, provider: str, model: str | None = None) -> int:
        """Look up the RPM limit for *provider*."""
        _ = model
        key = f"RIVALENS_LLM_RPM_LIMIT_{provider.upper()}"
        val = os.getenv(key)
        if val is not None:
            try:
                return int(val)
            except ValueError:
                pass
        return int(os.getenv("RIVALENS_LLM_RPM_LIMIT", "0"))

    def _get_redis(self) -> Any | None:
        if self._redis_init_attempted:
            return self._redis
        self._redis_init_attempted = True

        redis_url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
        try:
            import redis as _redis

            self._redis = _redis.from_url(redis_url, decode_responses=True)
            self._redis.ping()
            self._script = self._redis.register_script(_LUA_TOKEN_BUCKET)
        except Exception:
            logger.warning("Redis unavailable for LLM rate limiter, disabling")
            self._redis = None
        return self._redis


# ── singleton access ──────────────────────────────────────────────

_limiter: LLMRateLimiter | None = None


def get_llm_rate_limiter() -> LLMRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = LLMRateLimiter()
    return _limiter
