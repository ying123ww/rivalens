from typing import Any
from colorama import Fore, Style

from rivalens.research.utils.workers import WorkerPool
from rivalens.research.source_cache import ScrapedSourceCache
from ..scraper import Scraper
from ..config.config import Config
from ..utils.logger import get_formatted_logger

logger = get_formatted_logger()


async def scrape_urls(
    urls,
    cfg: Config,
    worker_pool: WorkerPool,
    trace_context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Scrapes the urls
    Args:
        urls: List of urls
        cfg: Config (optional)

    Returns:
        tuple[list[dict[str, Any]], list[dict[str, Any]]]: tuple containing scraped content and images

    """
    scraped_data = []
    images = []
    cache = _build_scraped_source_cache()
    user_agent = (
        cfg.user_agent
        if cfg
        else "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )

    try:
        cached_data, urls_to_scrape = _split_cached_sources(urls, cache)
        if urls_to_scrape:
            scraper = Scraper(
                urls_to_scrape,
                user_agent,
                cfg.scraper,
                worker_pool=worker_pool,
                trace_context=trace_context,
            )
            scraped_data = await scraper.run()
        else:
            scraped_data = []
        _store_scraped_sources(scraped_data, cache)
        scraped_data = [*cached_data, *scraped_data]
        for item in scraped_data:
            if 'image_urls' in item:
                images.extend(item['image_urls'])
        if cache:
            cache_hits = sum(
                1
                for item in scraped_data
                if (item.get("source_cache") or {}).get("status") == "hit"
            )
            if cache_hits:
                logger.info(
                    "Scraped source cache served %s page(s); fetched %s fresh page(s).",
                    cache_hits,
                    len(scraped_data) - cache_hits,
                )
    except Exception as e:
        print(f"{Fore.RED}Error in scrape_urls: {e}{Style.RESET_ALL}")

    return scraped_data, images


def _build_scraped_source_cache() -> ScrapedSourceCache | None:
    try:
        return ScrapedSourceCache.from_env()
    except Exception as exc:
        logger.warning("Scraped source cache unavailable: %s", exc)
        return None


def _split_cached_sources(
    urls: list[str],
    cache: ScrapedSourceCache | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if cache is None:
        return [], list(dict.fromkeys(urls))

    cached_data: list[dict[str, Any]] = []
    urls_to_scrape: list[str] = []
    pending_canonical_urls: set[str] = set()

    for url in urls:
        try:
            lookup = cache.lookup(url)
        except Exception as exc:
            logger.warning("Scraped source cache lookup failed for %s: %s", url, exc)
            if url not in pending_canonical_urls:
                pending_canonical_urls.add(url)
                urls_to_scrape.append(url)
            continue
        if lookup.source is not None:
            cached_data.append(lookup.source)
            continue

        canonical_url = lookup.identity.canonical_url or url
        if canonical_url in pending_canonical_urls:
            continue
        pending_canonical_urls.add(canonical_url)
        urls_to_scrape.append(url)

    return cached_data, urls_to_scrape


def _store_scraped_sources(
    scraped_data: list[dict[str, Any]],
    cache: ScrapedSourceCache | None,
) -> None:
    if cache is None:
        return

    for item in scraped_data:
        try:
            metadata = cache.upsert(item)
        except Exception as exc:
            logger.warning(
                "Scraped source cache write failed for %s: %s",
                item.get("url"),
                exc,
            )
            continue
        if not metadata:
            continue
        item["source_cache"] = metadata
        item["canonical_url"] = metadata["canonical_url"]
        item["source_domain"] = metadata["domain"]
        item["scraped_content_sha256"] = metadata["content_sha256"]


async def filter_urls(urls: list[str], config: Config) -> list[str]:
    """
    Filter URLs based on configuration settings.

    Args:
        urls (list[str]): List of URLs to filter.
        config (Config): Configuration object.

    Returns:
        list[str]: Filtered list of URLs.
    """
    filtered_urls = []
    for url in urls:
        # Add your filtering logic here
        # For example, you might want to exclude certain domains or URL patterns
        if not any(excluded in url for excluded in config.excluded_domains):
            filtered_urls.append(url)
    return filtered_urls

async def extract_main_content(html_content: str) -> str:
    """
    Extract the main content from HTML.

    Args:
        html_content (str): Raw HTML content.

    Returns:
        str: Extracted main content.
    """
    # Implement content extraction logic here
    # This could involve using libraries like BeautifulSoup or custom parsing logic
    # For now, we'll just return the raw HTML as a placeholder
    return html_content

async def process_scraped_data(scraped_data: list[dict[str, Any]], config: Config) -> list[dict[str, Any]]:
    """
    Process the scraped data to extract and clean the main content.

    Args:
        scraped_data (list[dict[str, Any]]): List of dictionaries containing scraped data.
        config (Config): Configuration object.

    Returns:
        list[dict[str, Any]]: Processed scraped data.
    """
    processed_data = []
    for item in scraped_data:
        if item['status'] == 'success':
            main_content = await extract_main_content(item['content'])
            processed_data.append({
                'url': item['url'],
                'content': main_content,
                'status': 'success'
            })
        else:
            processed_data.append(item)
    return processed_data
