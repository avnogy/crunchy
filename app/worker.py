from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class JobWorker:
    def __init__(
        self,
        queue: asyncio.Queue,
        handler,
        workers: int = 2,
    ) -> None:
        self.queue = queue
        self.handler = handler
        self.workers = workers
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        logger.info("Starting %d worker(s)", self.workers)
        self._tasks = [asyncio.create_task(self._work()) for _ in range(self.workers)]

    async def _work(self) -> None:
        while True:
            job = await self.queue.get()
            try:
                logger.debug("Processing job %s", job.id)
                await self.handler(job)
            except Exception:
                logger.exception("Error processing job %s", job.id)
            finally:
                self.queue.task_done()

    async def stop(self) -> None:
        logger.info("Stopping workers")
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
