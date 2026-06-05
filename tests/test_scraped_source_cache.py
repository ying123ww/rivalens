"""Tests for crawler-level scraped source caching."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from rivalens.research.actions import web_scraping
from rivalens.research.actions.web_scraping import scrape_urls
from rivalens.research.source_cache import ScrapedSourceCache
from rivalens.research.source_identity import identify_source_url


class DummyConfig:
    user_agent = "rivalens-test-agent"
    scraper = "dummy"


class FakeScraper:
    calls: list[list[str]] = []

    def __init__(
        self,
        urls: list[str],
        user_agent: str,
        scraper: str,
        worker_pool: Any,
        trace_context: dict[str, Any] | None = None,
    ) -> None:
        self.urls = urls
        self.user_agent = user_agent
        self.scraper = scraper
        self.worker_pool = worker_pool
        self.trace_context = trace_context
        self.__class__.calls.append(list(urls))

    async def run(self) -> list[dict[str, Any]]:
        return [
            {
                "url": url,
                "raw_content": (
                    "This cached source contains enough public page content "
                    f"for crawler cache testing. Source URL: {url}. "
                )
                * 3,
                "image_urls": [{"url": f"{url}/image.png", "score": 0.5}],
                "title": "Cached Source",
                "scraper_name": "FakeScraper",
            }
            for url in self.urls
        ]


def test_source_identity_canonicalizes_tracking_url():
    identity = identify_source_url(
        "https://www.Example.com/pricing/?utm_source=newsletter&plan=pro#faq"
    )

    assert identity.domain == "example.com"
    assert identity.canonical_url == "https://example.com/pricing?plan=pro"


def test_scrape_urls_reuses_fresh_canonical_cache(monkeypatch, tmp_path):
    FakeScraper.calls = []
    monkeypatch.setattr(web_scraping, "Scraper", FakeScraper)
    monkeypatch.setenv("RIVALENS_SCRAPED_SOURCE_CACHE_ENABLED", "true")
    monkeypatch.setenv(
        "RIVALENS_SCRAPED_SOURCE_CACHE_PATH",
        str(tmp_path / "scraped_source_cache.sqlite3"),
    )
    monkeypatch.setenv("RIVALENS_SCRAPED_SOURCE_CACHE_TTL_SECONDS", "3600")

    first_url = "https://example.com/pricing?utm_source=initial"
    second_url = "https://www.example.com/pricing/?utm_campaign=followup"
    first_sources, _ = asyncio.run(scrape_urls([first_url], DummyConfig(), object()))
    second_sources, _ = asyncio.run(scrape_urls([second_url], DummyConfig(), object()))

    assert FakeScraper.calls == [[first_url]]
    assert first_sources[0]["source_cache"]["status"] == "stored"
    assert second_sources[0]["source_cache"]["status"] == "hit"
    assert second_sources[0]["url"] == second_url
    assert second_sources[0]["raw_content"] == first_sources[0]["raw_content"]
    assert second_sources[0]["canonical_url"] == "https://example.com/pricing"


def test_scrape_urls_refetches_stale_cache(monkeypatch, tmp_path):
    FakeScraper.calls = []
    monkeypatch.setattr(web_scraping, "Scraper", FakeScraper)
    monkeypatch.setenv("RIVALENS_SCRAPED_SOURCE_CACHE_ENABLED", "true")
    monkeypatch.setenv(
        "RIVALENS_SCRAPED_SOURCE_CACHE_PATH",
        str(tmp_path / "scraped_source_cache.sqlite3"),
    )
    monkeypatch.setenv("RIVALENS_SCRAPED_SOURCE_CACHE_TTL_SECONDS", "0")

    url = "https://example.com/docs"
    first_sources, _ = asyncio.run(scrape_urls([url], DummyConfig(), object()))
    second_sources, _ = asyncio.run(scrape_urls([url], DummyConfig(), object()))

    assert FakeScraper.calls == [[url], [url]]
    assert first_sources[0]["source_cache"]["status"] == "stored"
    assert second_sources[0]["source_cache"]["status"] == "stored"


def test_scraped_source_cache_deletes_expired_rows(tmp_path):
    cache = ScrapedSourceCache(tmp_path / "scraped_source_cache.sqlite3", ttl_seconds=86400)
    fetched_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    url = "https://example.com/old-page"
    cache.upsert(
        {
            "url": url,
            "raw_content": "Enough content for this old cached page. " * 5,
            "image_urls": [],
            "title": "Old Page",
            "scraper_name": "FakeScraper",
        },
        now=fetched_at,
    )

    assert cache.lookup(url, now=fetched_at + timedelta(hours=1)).status == "hit"
    assert cache.delete_expired(now=fetched_at + timedelta(days=2)) == 1
    assert cache.lookup(url, now=fetched_at + timedelta(days=2)).status == "miss"
