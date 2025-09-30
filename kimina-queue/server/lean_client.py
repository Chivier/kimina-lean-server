import asyncio
from typing import Any

import httpx
from loguru import logger


class LeanServerClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Initialize the HTTP client."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(self.timeout),
        )
        logger.info(f"Lean server client initialized for {self.base_url}")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def check_health(self) -> bool:
        """Check if the Lean server is healthy."""
        if not self._client:
            return False

        try:
            response = await self._client.get("/health", timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return False

    async def post(self, endpoint: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Send a POST request to the Lean server. Returns (response_data, status_code)."""
        if not self._client:
            raise RuntimeError("Client not initialized. Call start() first.")

        try:
            response = await self._client.post(endpoint, json=payload)
            return response.json(), response.status_code
        except httpx.TimeoutException as e:
            logger.error(f"Request to {endpoint} timed out: {e}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"HTTP error for {endpoint}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error for {endpoint}: {e}")
            raise

    async def wait_for_ready(self, max_wait: float = 60.0, check_interval: float = 2.0) -> bool:
        """Wait for the Lean server to become ready."""
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < max_wait:
            if await self.check_health():
                logger.info("Lean server is ready")
                return True
            await asyncio.sleep(check_interval)

        logger.error(f"Lean server did not become ready within {max_wait}s")
        return False