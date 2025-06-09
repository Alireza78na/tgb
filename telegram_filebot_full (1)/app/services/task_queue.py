import asyncio
from typing import Callable, Any, Awaitable, Dict

class TaskQueue:
    def __init__(self, concurrency: int = 3):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._concurrency = concurrency
        self._workers = []
        self._tasks: Dict[str, asyncio.Task] = {}
        self._stop = False

    async def start(self):
        for _ in range(self._concurrency):
            self._workers.append(asyncio.create_task(self._worker()))

    async def stop(self):
        self._stop = True
        await self._queue.join()
        for w in self._workers:
            w.cancel()

    async def _worker(self):
        while True:
            func, args, kwargs, done = await self._queue.get()
            try:
                await func(*args, **kwargs)
            finally:
                self._queue.task_done()
                if done:
                    done.set_result(True)

    async def add_task(self, coro: Callable[..., Awaitable[Any]], *args, **kwargs):
        done = asyncio.get_event_loop().create_future()
        await self._queue.put((coro, args, kwargs, done))
        return done
