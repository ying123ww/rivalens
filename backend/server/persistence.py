"""Persistence endpoint configuration.

This module intentionally does not create tables or open connections. Docker
creates the PostgreSQL database and Redis instance; application code can import
this config when persistence is wired in later.
"""

import os
from dataclasses import dataclass


DEFAULT_DATABASE_URL = (
    "postgresql://rivalens:rivalens_password@postgres:5432/rivalens"
)
DEFAULT_REDIS_URL = "redis://redis:6379/0"


@dataclass(frozen=True)
class PersistenceConfig:
    database_url: str
    redis_url: str


def get_persistence_config() -> PersistenceConfig:
    return PersistenceConfig(
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        redis_url=os.getenv("REDIS_URL", DEFAULT_REDIS_URL),
    )


def redact_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url

    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"
