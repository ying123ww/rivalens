from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from rivalens.research.utils.llm_rate_limiter import (
    LLMRateLimiter,
    _LUA_TOKEN_BUCKET,
)


class FakeAsyncScript:
    def __init__(self, results: list[list[int]]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, list[str]]] = []

    async def __call__(
        self,
        *,
        keys: list[str],
        args: list[str],
    ) -> list[int]:
        self.calls.append({"keys": keys, "args": args})
        return self.results.pop(0)


class FakeAsyncRedis:
    def __init__(
        self,
        script_results: list[list[int]] | None = None,
        ping_error: Exception | None = None,
    ) -> None:
        self.ping_error = ping_error
        self.ping_count = 0
        self.closed = False
        self.registered_script = ""
        self.script = FakeAsyncScript(script_results or [[1, 9, 0]])

    async def ping(self) -> bool:
        self.ping_count += 1
        if self.ping_error is not None:
            raise self.ping_error
        return True

    def register_script(self, script: str) -> FakeAsyncScript:
        self.registered_script = script
        return self.script

    async def aclose(self) -> None:
        self.closed = True


class LLMRateLimiterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        LLMRateLimiter._instance = None

    def tearDown(self) -> None:
        LLMRateLimiter._instance = None

    async def test_acquire_uses_async_redis_and_preserves_token_bucket(self) -> None:
        client = FakeAsyncRedis()
        limiter = LLMRateLimiter()

        with (
            patch.dict(
                os.environ,
                {"RIVALENS_LLM_RPM_LIMIT_OPENAI": "60"},
                clear=False,
            ),
            patch("redis.asyncio.from_url", return_value=client),
        ):
            acquired = await limiter.acquire("openai")

        self.assertTrue(acquired)
        self.assertEqual(client.ping_count, 1)
        self.assertEqual(client.registered_script, _LUA_TOKEN_BUCKET)
        self.assertEqual(
            client.script.calls[0]["keys"],
            ["llm:rate_limit:openai"],
        )
        self.assertEqual(client.script.calls[0]["args"], ["60", "1.0", "1"])
        await limiter.aclose()
        self.assertTrue(client.closed)

    async def test_acquire_waits_asynchronously_until_token_is_available(self) -> None:
        client = FakeAsyncRedis(
            script_results=[
                [0, 0, 50],
                [1, 9, 0],
            ],
        )
        limiter = LLMRateLimiter()

        with (
            patch.dict(
                os.environ,
                {"RIVALENS_LLM_RPM_LIMIT_OPENAI": "60"},
                clear=False,
            ),
            patch("redis.asyncio.from_url", return_value=client),
            patch(
                "rivalens.research.utils.llm_rate_limiter.asyncio.sleep",
                new=AsyncMock(),
            ) as sleep,
        ):
            acquired = await limiter.acquire("openai")

        self.assertTrue(acquired)
        sleep.assert_awaited_once_with(0.05)
        self.assertEqual(len(client.script.calls), 2)
        await limiter.aclose()

    async def test_redis_initialization_failure_keeps_fail_open_behavior(self) -> None:
        client = FakeAsyncRedis(ping_error=ConnectionError("unavailable"))
        limiter = LLMRateLimiter()

        with (
            patch.dict(
                os.environ,
                {"RIVALENS_LLM_RPM_LIMIT_OPENAI": "60"},
                clear=False,
            ),
            patch("redis.asyncio.from_url", return_value=client),
        ):
            acquired = await limiter.acquire("openai")

        self.assertTrue(acquired)
        self.assertTrue(client.closed)

    async def test_concurrent_acquires_share_one_async_redis_client(self) -> None:
        client = FakeAsyncRedis(
            script_results=[
                [1, 9, 0],
                [1, 8, 0],
            ],
        )
        limiter = LLMRateLimiter()

        with (
            patch.dict(
                os.environ,
                {"RIVALENS_LLM_RPM_LIMIT_OPENAI": "60"},
                clear=False,
            ),
            patch("redis.asyncio.from_url", return_value=client) as from_url,
        ):
            results = await asyncio.gather(
                limiter.acquire("openai"),
                limiter.acquire("openai"),
            )

        self.assertEqual(results, [True, True])
        from_url.assert_called_once()
        self.assertEqual(client.ping_count, 1)
        self.assertEqual(len(client.script.calls), 2)
        await limiter.aclose()

    async def test_disabled_limit_does_not_create_redis_client(self) -> None:
        limiter = LLMRateLimiter()

        with (
            patch.dict(
                os.environ,
                {"RIVALENS_LLM_RPM_LIMIT_OPENAI": "0"},
                clear=False,
            ),
            patch("redis.asyncio.from_url") as from_url,
        ):
            acquired = await limiter.acquire("openai")

        self.assertTrue(acquired)
        from_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
