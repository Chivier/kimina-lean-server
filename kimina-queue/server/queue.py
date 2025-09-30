import asyncio
from collections import deque
from time import time
from typing import Any

from loguru import logger

from .models import QueuedRequest


class RequestQueue:
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._queue: deque[QueuedRequest] = deque()
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Condition(self._lock)
        self._request_counter = 0

    async def enqueue(self, endpoint: str, payload: dict[str, Any]) -> str:
        """Add a request to the queue. Returns request_id."""
        async with self._lock:
            if len(self._queue) >= self.max_size:
                raise RuntimeError(f"Queue is full (max size: {self.max_size})")

            self._request_counter += 1
            request_id = f"req-{self._request_counter}-{int(time() * 1000)}"

            queued_request = QueuedRequest(
                request_id=request_id,
                endpoint=endpoint,
                payload=payload,
                timestamp=time(),
            )
            self._queue.append(queued_request)
            logger.info(f"Enqueued request {request_id} for {endpoint}")

            self._not_empty.notify()
            return request_id

    async def dequeue(self, timeout: float | None = None) -> QueuedRequest | None:
        """Remove and return the first request from the queue. Waits if queue is empty."""
        async with self._not_empty:
            while len(self._queue) == 0:
                if timeout is not None:
                    try:
                        await asyncio.wait_for(self._not_empty.wait(), timeout)
                    except asyncio.TimeoutError:
                        return None
                else:
                    await self._not_empty.wait()

            return self._queue.popleft()

    async def size(self) -> int:
        """Return current queue size."""
        async with self._lock:
            return len(self._queue)

    async def clear(self) -> None:
        """Clear all requests from the queue."""
        async with self._lock:
            self._queue.clear()
            logger.info("Queue cleared")