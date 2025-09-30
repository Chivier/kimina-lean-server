import asyncio
import sys
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from loguru import logger

from .lean_client import LeanServerClient
from .lean_manager import LeanServerManager
from .models import QueueStats, ServerStatus
from .queue import RequestQueue
from .settings import settings

# Configure loguru
logger.remove()
logger.add(sys.stderr, level=settings.log_level)


class QueueService:
    def __init__(self):
        self.queue = RequestQueue(max_size=settings.queue_max_size)
        self.lean_client = LeanServerClient(
            base_url=settings.lean_server_url,
            api_key=settings.lean_server_api_key,
            timeout=settings.queue_request_timeout,
        )
        self.lean_manager = LeanServerManager(
            env_path=settings.lean_server_env_path,
        )
        self._worker_task: asyncio.Task[None] | None = None
        self._pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}

    async def start(self) -> None:
        """Start the queue service."""
        logger.info("Starting queue service...")
        await self.lean_client.start()

        # Wait for Lean server to be ready
        if not await self.lean_client.wait_for_ready():
            logger.error("Lean server is not ready. Ensure it is running.")

        # Start worker task
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("Queue service started")

    async def stop(self) -> None:
        """Stop the queue service."""
        logger.info("Stopping queue service...")

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        await self.lean_client.close()
        logger.info("Queue service stopped")

    async def _worker(self) -> None:
        """Worker task that processes queued requests."""
        logger.info("Worker task started")

        while True:
            try:
                # Wait for server to be running (check via HTTP health, not process status)
                if self.lean_manager.status == ServerStatus.RESTARTING or not await self.lean_client.check_health():
                    logger.info("Waiting for Lean server to be ready...")
                    await asyncio.sleep(2)
                    continue

                # Dequeue next request
                queued_request = await self.queue.dequeue(timeout=1.0)
                if queued_request is None:
                    continue

                request_id = queued_request.request_id
                logger.info(f"Processing request {request_id}")

                try:
                    # Send request to Lean server
                    response_data, status_code = await self.lean_client.post(
                        queued_request.endpoint, queued_request.payload
                    )

                    # Check for OOM errors
                    if status_code >= 500:
                        if await self._handle_potential_oom(response_data):
                            # Re-queue the request
                            logger.info(f"Re-queueing request {request_id} after OOM recovery")
                            new_request_id = await self.queue.enqueue(
                                queued_request.endpoint, queued_request.payload
                            )

                            # Transfer the future to the new request
                            if request_id in self._pending_requests:
                                future = self._pending_requests.pop(request_id)
                                self._pending_requests[new_request_id] = future
                            continue

                    # Complete the request
                    if request_id in self._pending_requests:
                        future = self._pending_requests.pop(request_id)
                        if not future.done():
                            future.set_result({"data": response_data, "status": status_code})

                except Exception as e:
                    logger.error(f"Error processing request {request_id}: {e}")
                    if request_id in self._pending_requests:
                        future = self._pending_requests.pop(request_id)
                        if not future.done():
                            future.set_exception(e)

            except asyncio.CancelledError:
                logger.info("Worker task cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in worker: {e}")
                await asyncio.sleep(1)

    async def _handle_potential_oom(self, response_data: dict[str, Any]) -> bool:
        """
        Check if the error is an OOM error and handle it.
        Returns True if OOM was detected and handled, False otherwise.
        """
        # Check if response indicates OOM
        error_msg = str(response_data.get("detail", "")).lower()
        if "oom" in error_msg or "out of memory" in error_msg or "memory" in error_msg:
            logger.warning(f"Detected OOM error: {error_msg}")
            self.lean_manager.increment_oom_count()

            # Restart with reduced MAX_REPLS
            logger.info("Restarting Lean server with reduced MAX_REPLS...")
            if not await self.lean_manager.restart(reduce_max_repls=True):
                logger.error("Failed to restart Lean server")
                return False

            # Wait for server to be ready
            if not await self.lean_client.wait_for_ready(max_wait=120.0):
                logger.error("Lean server did not become ready after restart")
                return False

            return True

        return False

    async def submit_request(
        self, endpoint: str, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], int]:
        """
        Submit a request to the queue and wait for the result.
        Returns (response_data, status_code).
        """
        request_id = await self.queue.enqueue(endpoint, payload)

        # Create a future for this request
        future: asyncio.Future[dict[str, Any]] = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=settings.queue_request_timeout)
            return result["data"], result["status"]
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise HTTPException(504, "Request timed out")

    async def get_stats(self) -> QueueStats:
        """Get queue statistics."""
        return QueueStats(
            queue_size=await self.queue.size(),
            server_status=self.lean_manager.status,
            current_max_repls=self.lean_manager.current_max_repls or 0,
            default_max_repls=self.lean_manager.default_max_repls or 0,
            oom_count=self.lean_manager.oom_count,
        )


# Global service instance
service: QueueService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Lifespan context manager for FastAPI."""
    global service
    service = QueueService()
    await service.start()
    yield
    await service.stop()


# Create FastAPI app
app = FastAPI(
    title="Kimina Queue Service",
    description="Message queue service for managing kimina-lean-server",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/stats")
async def stats() -> QueueStats:
    """Get queue statistics."""
    if service is None:
        raise HTTPException(500, "Service not initialized")
    return await service.get_stats()


@app.post("/api/check")
async def check(payload: dict[str, Any]) -> dict[str, Any]:
    """Proxy /api/check requests to Lean server."""
    if service is None:
        raise HTTPException(500, "Service not initialized")

    try:
        response_data, status_code = await service.submit_request("/api/check", payload)
        if status_code != 200:
            raise HTTPException(status_code, response_data)
        return response_data
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error proxying request: {e}")
        raise HTTPException(500, str(e)) from e


@app.post("/api/restart")
async def restart_server(reduce_max_repls: bool = False) -> dict[str, str]:
    """Manually restart the Lean server."""
    if service is None:
        raise HTTPException(500, "Service not initialized")

    success = await service.lean_manager.restart(reduce_max_repls=reduce_max_repls)
    if success:
        await service.lean_client.wait_for_ready()
        return {"status": "ok", "message": "Lean server restarted"}
    raise HTTPException(500, "Failed to restart Lean server")


@app.post("/api/restart-default")
async def restart_default() -> dict[str, str]:
    """Restart the Lean server with default MAX_REPLS."""
    if service is None:
        raise HTTPException(500, "Service not initialized")

    success = await service.lean_manager.restart_to_default()
    if success:
        await service.lean_client.wait_for_ready()
        return {"status": "ok", "message": "Lean server restarted with default MAX_REPLS"}
    raise HTTPException(500, "Failed to restart Lean server")


def main():
    """Main entry point."""
    uvicorn.run(
        "server.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()