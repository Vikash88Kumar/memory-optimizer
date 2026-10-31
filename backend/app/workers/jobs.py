"""Lightweight in-process background worker (asyncio).

Memory extraction, episode summarisation and rolling summaries run after the reply is returned, so
the user never waits for them. Jobs for the same user are serialised with a per-user lock (no
consolidation races) and retried with exponential backoff. For a single-instance hackathon deployment
this avoids running Redis/Celery; for horizontal scaling swap this runner for a queue-backed worker."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Awaitable, Callable

from app.core.logging import log


class JobRunner:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._pending: dict[str, int] = defaultdict(int)
        self.completed = 0
        self.failed = 0

    def submit(self, user_id: str, name: str, factory: Callable[[], Awaitable[None]], *, retries: int = 2,
               on_failure: Callable[[Exception], Awaitable[None]] | None = None) -> None:
        self._pending[user_id] += 1
        task = asyncio.create_task(self._run(user_id, name, factory, retries, on_failure))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, user_id, name, factory, retries, on_failure) -> None:
        try:
            async with self._locks[user_id]:
                for attempt in range(retries + 1):
                    try:
                        await factory()
                        self.completed += 1
                        return
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Job %s failed (attempt %d/%d): %s", name, attempt + 1, retries + 1, type(exc).__name__)
                        if attempt == retries:
                            self.failed += 1
                            if on_failure:
                                try:
                                    await on_failure(exc)
                                except Exception:  # noqa: BLE001
                                    log.exception("on_failure handler for %s failed", name)
                            return
                        await asyncio.sleep(0.2 * (2**attempt))
        finally:
            self._pending[user_id] -= 1

    def pending(self, user_id: str | None = None) -> int:
        if user_id is None:
            return sum(self._pending.values())
        return self._pending.get(user_id, 0)

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


runner = JobRunner()
