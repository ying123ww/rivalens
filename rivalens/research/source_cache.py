"""Persistent cache for raw scraped source pages."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from rivalens.research.source_identity import SourceIdentity, identify_source_url


SCRAPED_SOURCE_CACHE_ENABLED_ENV = "RIVALENS_SCRAPED_SOURCE_CACHE_ENABLED"
SCRAPED_SOURCE_CACHE_PATH_ENV = "RIVALENS_SCRAPED_SOURCE_CACHE_PATH"
SCRAPED_SOURCE_CACHE_TTL_SECONDS_ENV = "RIVALENS_SCRAPED_SOURCE_CACHE_TTL_SECONDS"
DEFAULT_SCRAPED_SOURCE_CACHE_PATH = "/tmp/rivalens/scraped_source_cache.sqlite3"
DEFAULT_SCRAPED_SOURCE_CACHE_TTL_SECONDS = 24 * 60 * 60

CacheStatus = Literal["hit", "miss", "stale", "stored", "disabled"]


@dataclass(frozen=True)
class ScrapedSourceCacheLookup:
    status: CacheStatus
    identity: SourceIdentity
    source: dict[str, Any] | None = None


class ScrapedSourceCache:
    """SQLite-backed cache for full page content before EvidenceItem review."""

    def __init__(self, path: str | Path, ttl_seconds: int) -> None:
        self.path = Path(path)
        self.ttl_seconds = max(0, int(ttl_seconds))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        self.delete_expired()

    @classmethod
    def from_env(cls) -> "ScrapedSourceCache | None":
        if not _env_flag(SCRAPED_SOURCE_CACHE_ENABLED_ENV, default=True):
            return None
        path = os.getenv(SCRAPED_SOURCE_CACHE_PATH_ENV, DEFAULT_SCRAPED_SOURCE_CACHE_PATH)
        ttl_seconds = _int_env(
            SCRAPED_SOURCE_CACHE_TTL_SECONDS_ENV,
            DEFAULT_SCRAPED_SOURCE_CACHE_TTL_SECONDS,
        )
        return cls(path=path, ttl_seconds=ttl_seconds)

    def lookup(self, url: str, *, now: datetime | None = None) -> ScrapedSourceCacheLookup:
        identity = identify_source_url(url)
        if not identity.canonical_url:
            return ScrapedSourceCacheLookup(status="miss", identity=identity)

        row = self._select(identity.canonical_url)
        if row is None:
            return ScrapedSourceCacheLookup(status="miss", identity=identity)

        current_time = now or _utcnow()
        expires_at = _parse_datetime(row["expires_at"])
        if expires_at <= current_time:
            self._delete(identity.canonical_url)
            return ScrapedSourceCacheLookup(status="stale", identity=identity)

        return ScrapedSourceCacheLookup(
            status="hit",
            identity=identity,
            source=self._row_to_source(row, requested_url=url, status="hit"),
        )

    def upsert(
        self,
        source: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        url = str(source.get("url") or source.get("href") or "").strip()
        raw_content = str(source.get("raw_content") or source.get("content") or "")
        if not url or len(raw_content) < 100:
            return None

        identity = identify_source_url(url)
        if not identity.canonical_url:
            return None

        fetched_at = now or _utcnow()
        expires_at = fetched_at + timedelta(seconds=self.ttl_seconds)
        image_urls = source.get("image_urls") or []
        content_sha256 = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        metadata = {
            "scraper_name": source.get("scraper_name") or "",
        }
        values = {
            "canonical_url": identity.canonical_url,
            "original_url": url,
            "final_url": source.get("final_url") or url,
            "domain": identity.domain,
            "title": source.get("title") or "",
            "raw_content": raw_content,
            "image_urls": _json_dumps(image_urls),
            "content_sha256": content_sha256,
            "scraper_name": source.get("scraper_name") or "",
            "fetched_at": fetched_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "metadata": _json_dumps(metadata),
        }

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO scraped_source_cache (
                    canonical_url,
                    original_url,
                    final_url,
                    domain,
                    title,
                    raw_content,
                    image_urls,
                    content_sha256,
                    scraper_name,
                    fetched_at,
                    expires_at,
                    metadata
                )
                VALUES (
                    :canonical_url,
                    :original_url,
                    :final_url,
                    :domain,
                    :title,
                    :raw_content,
                    :image_urls,
                    :content_sha256,
                    :scraper_name,
                    :fetched_at,
                    :expires_at,
                    :metadata
                )
                ON CONFLICT(canonical_url) DO UPDATE SET
                    original_url = excluded.original_url,
                    final_url = excluded.final_url,
                    domain = excluded.domain,
                    title = excluded.title,
                    raw_content = excluded.raw_content,
                    image_urls = excluded.image_urls,
                    content_sha256 = excluded.content_sha256,
                    scraper_name = excluded.scraper_name,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at,
                    metadata = excluded.metadata
                """,
                values,
            )

        return self._cache_metadata(
            status="stored",
            identity=identity,
            requested_url=url,
            stored_url=url,
            fetched_at=fetched_at.isoformat(),
            expires_at=expires_at.isoformat(),
            content_sha256=content_sha256,
            scraper_name=values["scraper_name"],
        )

    def delete_expired(self, *, now: datetime | None = None) -> int:
        current_time = now or _utcnow()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM scraped_source_cache
                WHERE expires_at <= ?
                """,
                (current_time.isoformat(),),
            )
            return int(cursor.rowcount or 0)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scraped_source_cache (
                    canonical_url TEXT PRIMARY KEY,
                    original_url TEXT NOT NULL,
                    final_url TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    title TEXT NOT NULL,
                    raw_content TEXT NOT NULL,
                    image_urls TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    scraper_name TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_scraped_source_cache_domain
                ON scraped_source_cache(domain)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_scraped_source_cache_expires_at
                ON scraped_source_cache(expires_at)
                """
            )

    def _select(self, canonical_url: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT
                    canonical_url,
                    original_url,
                    final_url,
                    domain,
                    title,
                    raw_content,
                    image_urls,
                    content_sha256,
                    scraper_name,
                    fetched_at,
                    expires_at,
                    metadata
                FROM scraped_source_cache
                WHERE canonical_url = ?
                """,
                (canonical_url,),
            ).fetchone()

    def _delete(self, canonical_url: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM scraped_source_cache
                WHERE canonical_url = ?
                """,
                (canonical_url,),
            )

    def _row_to_source(
        self,
        row: sqlite3.Row,
        *,
        requested_url: str,
        status: CacheStatus,
    ) -> dict[str, Any]:
        identity = identify_source_url(requested_url)
        return {
            "url": requested_url,
            "raw_content": row["raw_content"],
            "image_urls": _json_loads(row["image_urls"], default=[]),
            "title": row["title"],
            "canonical_url": row["canonical_url"],
            "source_domain": row["domain"],
            "scraped_content_sha256": row["content_sha256"],
            "source_cache": self._cache_metadata(
                status=status,
                identity=identity,
                requested_url=requested_url,
                stored_url=row["original_url"],
                fetched_at=row["fetched_at"],
                expires_at=row["expires_at"],
                content_sha256=row["content_sha256"],
                scraper_name=row["scraper_name"],
            ),
        }

    def _cache_metadata(
        self,
        *,
        status: CacheStatus,
        identity: SourceIdentity,
        requested_url: str,
        stored_url: str,
        fetched_at: str,
        expires_at: str,
        content_sha256: str,
        scraper_name: str,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "canonical_url": identity.canonical_url,
            "domain": identity.domain,
            "requested_url": requested_url,
            "stored_url": stored_url,
            "fetched_at": fetched_at,
            "expires_at": expires_at,
            "content_sha256": content_sha256,
            "scraper_name": scraper_name,
        }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: str, *, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
