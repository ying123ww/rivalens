"""进程内、跨事件循环安全的异步并发闸门。"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator


class ProcessConcurrencyLimiter:
    """使用线程计数器为整个进程提供异步并发硬上限。

    通知式释放：槽位空出时通过 ``asyncio.Event`` 立即唤醒等待者，
    不再轮询，零 CPU 浪费且零延迟。
    """

    def __init__(
        self,
        limit: int,
        *,
        name: str,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.limit = limit
        self.name = name

        self._counter = limit
        self._cv = threading.Condition(threading.Lock())
        self._event = asyncio.Event()

        self._state_lock = threading.Lock()
        self._active = 0
        self._waiting = 0
        self._peak_active = 0

    # ── async 接口 ──────────────────────────────────────────────

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self._acquire()
        self._mark_acquired()
        try:
            yield
        finally:
            self._mark_released()
            self._release()

    async def _acquire(self) -> None:
        """获取一个槽位，无空闲槽时阻塞等待通知。"""
        waiting = False
        try:
            while True:
                with self._cv:
                    if self._counter > 0:
                        self._counter -= 1
                        return
                    if not waiting:
                        waiting = True
                        self._change_waiting(1)
                await self._event.wait()
        finally:
            if waiting:
                self._change_waiting(-1)

    def _release(self) -> None:
        """释放槽位并唤醒一个等待者。"""
        with self._cv:
            self._counter += 1
            self._event.set()
            self._cv.notify()
        self._event.clear()

    # ── 快照 ────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, int | str]:
        with self._state_lock:
            return {
                "name": self.name,
                "limit": self.limit,
                "active": self._active,
                "waiting": self._waiting,
                "peak_active": self._peak_active,
            }

    # ── 内部计数 ─────────────────────────────────────────────────

    def _change_waiting(self, delta: int) -> None:
        with self._state_lock:
            self._waiting += delta

    def _mark_acquired(self) -> None:
        with self._state_lock:
            self._active += 1
            self._peak_active = max(self._peak_active, self._active)

    def _mark_released(self) -> None:
        with self._state_lock:
            self._active -= 1
