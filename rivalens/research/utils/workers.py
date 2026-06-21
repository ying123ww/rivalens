import asyncio
import atexit
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from .concurrency import ProcessConcurrencyLimiter
from .rate_limiter import get_global_rate_limiter


_DEFAULT_PROCESS_SCRAPER_WORKERS = 24
_shared_resource_lock = threading.Lock()
_shared_scraper_executor: ThreadPoolExecutor | None = None
_shared_scraper_executor_pid: int | None = None
_shared_scraper_limiter: ProcessConcurrencyLimiter | None = None
_shared_scraper_limiter_pid: int | None = None


def get_shared_scraper_executor() -> ThreadPoolExecutor:
    """返回当前进程共享的抓取线程池。"""
    global _shared_scraper_executor
    global _shared_scraper_executor_pid

    current_pid = os.getpid()
    with _shared_resource_lock:
        if (
            _shared_scraper_executor is None
            or _shared_scraper_executor_pid != current_pid
        ):
            worker_count = _process_scraper_worker_count()
            _shared_scraper_executor = ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="rivalens-scraper",
            )
            _shared_scraper_executor_pid = current_pid
        return _shared_scraper_executor


def get_process_scraper_limiter() -> ProcessConcurrencyLimiter:
    """返回同步和异步抓取共同使用的进程级并发闸门。"""
    global _shared_scraper_limiter
    global _shared_scraper_limiter_pid

    current_pid = os.getpid()
    with _shared_resource_lock:
        worker_count = _process_scraper_worker_count()
        if (
            _shared_scraper_limiter is None
            or _shared_scraper_limiter_pid != current_pid
            or _shared_scraper_limiter.limit != worker_count
        ):
            _shared_scraper_limiter = ProcessConcurrencyLimiter(
                worker_count,
                name="scraper",
            )
            _shared_scraper_limiter_pid = current_pid
        return _shared_scraper_limiter


def shutdown_shared_scraper_executor(*, wait: bool = False) -> None:
    """关闭当前进程共享线程池，主要用于进程退出和测试清理。"""
    global _shared_scraper_executor
    global _shared_scraper_executor_pid
    global _shared_scraper_limiter
    global _shared_scraper_limiter_pid

    with _shared_resource_lock:
        executor = _shared_scraper_executor
        executor_pid = _shared_scraper_executor_pid
        _shared_scraper_executor = None
        _shared_scraper_executor_pid = None
        _shared_scraper_limiter = None
        _shared_scraper_limiter_pid = None

    if executor is not None and executor_pid == os.getpid():
        executor.shutdown(wait=wait)


def _process_scraper_worker_count() -> int:
    raw_value = os.getenv(
        "RIVALENS_SCRAPER_PROCESS_WORKERS",
        str(_DEFAULT_PROCESS_SCRAPER_WORKERS),
    )
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return _DEFAULT_PROCESS_SCRAPER_WORKERS


atexit.register(shutdown_shared_scraper_executor)


class WorkerPool:
    def __init__(self, max_workers: int, rate_limit_delay: float = 0.0):
        """
        Initialize WorkerPool with concurrency and rate limiting.

        Args:
            max_workers: Maximum number of concurrent workers
            rate_limit_delay: Minimum seconds between requests GLOBALLY (0 = no limit)
                             This delay is enforced across ALL WorkerPools to prevent
                             overwhelming rate-limited APIs.
                             Example: 6.0 for 10 req/min (Firecrawl free tier)

        Note:
            The rate_limit_delay is enforced GLOBALLY using a singleton rate limiter.
            This means if you have multiple concurrent ResearchEngine instances,
            they will all share the same rate limit, preventing API overload.
        """
        self.max_workers = max_workers
        self.rate_limit_delay = rate_limit_delay
        self.executor = get_shared_scraper_executor()
        self.process_limiter = get_process_scraper_limiter()
        self.semaphore = asyncio.Semaphore(max_workers)

        # Configure the global rate limiter
        # All WorkerPools share the same rate limiter instance
        global_limiter = get_global_rate_limiter()
        global_limiter.configure(rate_limit_delay)

    @asynccontextmanager
    async def throttle(self):
        """
        Throttle requests with both concurrency limiting and GLOBAL rate limiting.

        - Semaphore controls concurrent operations within THIS pool (how many at once)
        - Global rate limiter controls request frequency ACROSS ALL POOLS (global timing)

        This ensures that even with multiple concurrent ResearchEngine instances,
        the total request rate stays within limits.
        """
        async with self.semaphore:
            async with self.process_limiter.slot():
                # 所有 WorkerPool 共享同一个进程级启动频率限制器
                global_limiter = get_global_rate_limiter()
                await global_limiter.wait_if_needed()
                yield
