from __future__ import annotations

import os
import sys

from celery import Celery


def _ensure_import_paths() -> None:
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    for path in (repo_root, backend_root):
        if path not in sys.path:
            sys.path.insert(0, path)


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


_ensure_import_paths()

broker_url = (
    os.getenv("CELERY_BROKER_URL")
    or os.getenv("RIVALENS_CELERY_BROKER_URL")
    or os.getenv("REDIS_URL")
    or "redis://:123456@localhost:6380/0"
)
result_backend = (
    os.getenv("CELERY_RESULT_BACKEND")
    or os.getenv("RIVALENS_CELERY_RESULT_BACKEND")
    or broker_url
)

celery_app = Celery(
    "rivalens_backend",
    broker=broker_url,
    backend=result_backend,
    include=["backend.server.celery_tasks"],
)

celery_app.conf.update(
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    result_serializer="json",
    task_serializer="json",
    task_soft_time_limit=_env_int("RIVALENS_CELERY_TASK_SOFT_TIME_LIMIT", 3300),
    task_time_limit=_env_int("RIVALENS_CELERY_TASK_TIME_LIMIT", 3600),
    task_track_started=True,
    timezone="UTC",
    worker_prefetch_multiplier=_env_int("RIVALENS_CELERY_WORKER_PREFETCH", 1),
)
