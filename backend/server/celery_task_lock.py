from __future__ import annotations

import os
from typing import Any


DEFAULT_REDIS_URL = "redis://:123456@localhost:6380/0"
REPORT_LOCK_KEY_PREFIX = "rivalens:celery:report-lock"

_LUA_RELEASE_LOCK = """
-- 仅允许锁的当前持有者释放锁，防止旧任务删除新任务的锁
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def report_lock_ttl_seconds() -> int:
    configured = _positive_int(
        os.getenv("RIVALENS_CELERY_REPORT_LOCK_TTL_SECONDS"),
        default=0,
    )
    if configured:
        return configured
    task_time_limit = _positive_int(
        os.getenv("RIVALENS_CELERY_TASK_TIME_LIMIT"),
        default=3600,
    )
    return task_time_limit + 300


class ReportTaskLock:
    def __init__(
        self,
        redis_url: str | None = None,
        ttl_seconds: int | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self._redis = redis_client
        self._release_script: Any | None = None

    def try_acquire(
        self,
        research_id: str,
        owner_task_id: str,
    ) -> tuple[bool, str | None]:
        client = self._client()
        key = self.key(research_id)
        try:
            acquired = bool(
                client.set(
                    key,
                    owner_task_id,
                    nx=True,
                    ex=self.ttl_seconds or report_lock_ttl_seconds(),
                )
            )
            if acquired:
                return True, None
            current_owner = client.get(key)
        except Exception as exc:
            raise RuntimeError(
                f"Unable to acquire Celery report lock for {research_id}"
            ) from exc
        return False, str(current_owner) if current_owner else None

    def release(self, research_id: str, owner_task_id: str) -> bool:
        client = self._client()
        try:
            if self._release_script is None:
                self._release_script = client.register_script(_LUA_RELEASE_LOCK)
            released = self._release_script(
                keys=[self.key(research_id)],
                args=[owner_task_id],
            )
        except Exception as exc:
            raise RuntimeError(
                f"Unable to release Celery report lock for {research_id}"
            ) from exc
        return bool(released)

    @staticmethod
    def key(research_id: str) -> str:
        return f"{REPORT_LOCK_KEY_PREFIX}:{research_id}"

    def _client(self) -> Any:
        if self._redis is not None:
            return self._redis

        redis_url = (
            self.redis_url
            or os.getenv("RIVALENS_CELERY_LOCK_REDIS_URL")
            or os.getenv("REDIS_URL")
            or os.getenv("CELERY_BROKER_URL")
            or os.getenv("RIVALENS_CELERY_BROKER_URL")
            or DEFAULT_REDIS_URL
        )
        try:
            import redis

            self._redis = redis.from_url(redis_url, decode_responses=True)
            self._redis.ping()
        except Exception as exc:
            self._redis = None
            raise RuntimeError("Redis is unavailable for Celery report locking") from exc
        return self._redis


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
