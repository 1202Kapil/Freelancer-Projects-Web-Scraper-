"""Network transport, pacing semaphores, and access restriction handling."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


class AccessRestricted(Exception):
    """Raised when the storefront server denies access (HTTP 403 Forbidden)."""
    pass


class RequestBudgetExceeded(Exception):
    """Raised when max request budget is reached."""
    pass


class Fetcher:
    """Async HTTP transport with per-host concurrency pacing and retry limits."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_per_host: float = 1.0,  # requests per second
        per_host_concurrency: int = 1,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
        max_requests: Optional[int] = None,
    ):
        self.client = client
        self.rate_per_host = rate_per_host
        self.per_host_concurrency = max(1, int(per_host_concurrency or 1))
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_requests = max_requests if (max_requests is not None and max_requests > 0) else None
        self.request_count = 0
        self._delay = 1.0 / max(rate_per_host, 0.0001)
        self._rate_lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(self.per_host_concurrency)
        self._last_request_time = 0.0

    async def get(self, url: str) -> httpx.Response:
        """Issue GET request with rate limiting and exponential backoff on retryable status."""
        async with self._sem:
            async with self._rate_lock:
                if self.max_requests is not None and self.request_count >= self.max_requests:
                    raise RequestBudgetExceeded(f"Request budget of {self.max_requests} exceeded")
                self.request_count += 1

                now = time.time()
                elapsed = now - self._last_request_time
                if elapsed < self._delay:
                    await asyncio.sleep(self._delay - elapsed)
                self._last_request_time = time.time()

            for attempt in range(1, self.max_retries + 2):
                try:
                    resp = await self.client.get(url)
                    if resp.status_code == 403:
                        logger.error(f"[AccessRestricted] HTTP 403 Forbidden for: {url}")
                        raise AccessRestricted(f"Access denied by remote host (HTTP 403): {url}")
                    elif resp.status_code == 404:
                        return resp
                    elif resp.status_code in (429, 500, 502, 503, 504) and attempt <= self.max_retries:
                        backoff = (self.backoff_factor ** attempt) + random.uniform(0.1, 0.5)
                        logger.warning(f"[HTTP {resp.status_code}] Retrying {url} in {backoff:.2f}s (attempt {attempt}/{self.max_retries})")
                        await asyncio.sleep(backoff)
                        continue
                    return resp
                except (httpx.RequestError, httpx.TimeoutException) as e:
                    if attempt <= self.max_retries:
                        backoff = (self.backoff_factor ** attempt) + random.uniform(0.1, 0.5)
                        logger.warning(f"[NetError] {e} on {url}, retrying in {backoff:.2f}s")
                        await asyncio.sleep(backoff)
                    else:
                        raise
            raise httpx.RequestError(f"Exceeded max retries for {url}")
