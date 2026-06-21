"""
Global rate limiter for scraper requests.

Ensures that SCRAPER_RATE_LIMIT_DELAY is enforced globally across ALL WorkerPools,
not just per-pool. This prevents multiple concurrent researchers from overwhelming
rate-limited APIs like Firecrawl.
"""
import asyncio
import threading
import time
from typing import ClassVar


class GlobalRateLimiter:
    """
    Singleton global rate limiter.

    Ensures minimum delay between ANY scraper requests across the entire application,
    regardless of how many WorkerPools or ResearchEngine instances are active.
    """

    _instance: ClassVar['GlobalRateLimiter'] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the global rate limiter (only once)."""
        if self._initialized:
            return

        self.last_request_time = 0.0
        self.rate_limit_delay = 0.0
        self._initialized = True

    def configure(self, rate_limit_delay: float):
        """
        Configure the global rate limit delay.

        Args:
            rate_limit_delay: Minimum seconds between requests (0 = no limit)
        """
        self.rate_limit_delay = rate_limit_delay

    async def wait_if_needed(self):
        """
        Wait if needed to enforce global rate limiting.

        This method ensures that regardless of how many WorkerPools are active,
        the SCRAPER_RATE_LIMIT_DELAY is respected globally.
        """
        if self.rate_limit_delay <= 0:
            return  # No rate limiting

        while True:
            with self._lock:
                current_time = time.monotonic()
                time_since_last = current_time - self.last_request_time
                sleep_time = self.rate_limit_delay - time_since_last
                if sleep_time <= 0:
                    self.last_request_time = current_time
                    return
            await asyncio.sleep(sleep_time)

    def reset(self):
        """Reset the rate limiter state (useful for testing)."""
        self.last_request_time = 0.0


# Singleton instance
_global_rate_limiter = GlobalRateLimiter()


def get_global_rate_limiter() -> GlobalRateLimiter:
    """Get the global rate limiter singleton instance."""
    return _global_rate_limiter
