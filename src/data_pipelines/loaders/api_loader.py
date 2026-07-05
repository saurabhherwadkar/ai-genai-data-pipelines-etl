"""
API loader.

Sends processed records to external REST APIs via HTTP POST.
Supports authentication, retry logic, and rate limiting.
"""

import asyncio
from typing import Any, Optional

from data_pipelines.loaders.base import BaseLoader
from data_pipelines.models.schemas import LoadResult
from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)


class APILoader(BaseLoader):
    """
    Loads processed data to an external REST API.

    Sends records via HTTP POST with configurable authentication,
    retry logic with exponential backoff, and rate limiting.
    """

    def __init__(
        self,
        base_url: str,
        endpoint: str = "/api/records",
        auth_token: Optional[str] = None,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        rate_limit_per_second: float = 10.0,
        timeout: float = 30.0,
    ) -> None:
        """
        Initialize API loader.

        Args:
            base_url: Base URL of the target API.
            endpoint: API endpoint path for record submission.
            auth_token: Bearer token for authentication.
            headers: Additional HTTP headers.
            max_retries: Maximum retry attempts on failure.
            retry_delay: Base delay between retries (exponential backoff).
            rate_limit_per_second: Maximum requests per second.
            timeout: Request timeout in seconds.
        """
        self._base_url = base_url.rstrip("/")
        self._endpoint = endpoint
        self._auth_token = auth_token
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._rate_limit_interval = 1.0 / rate_limit_per_second
        self._timeout = timeout
        self._headers = headers or {}
        if auth_token:
            self._headers["Authorization"] = f"Bearer {auth_token}"
        self._headers.setdefault("Content-Type", "application/json")
        self._last_request_time = 0.0

    async def load(self, data: dict[str, Any], document_id: str) -> LoadResult:
        """Send a single record to the API."""
        url = f"{self._base_url}{self._endpoint}"
        payload = {"document_id": document_id, "data": data}

        for attempt in range(self._max_retries):
            try:
                # Rate limiting
                await self._rate_limit()

                import httpx

                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(url, json=payload, headers=self._headers)

                if response.status_code in (200, 201, 202):
                    logger.info("Record sent to API", document_id=document_id, status=response.status_code)
                    return LoadResult(
                        document_id=document_id,
                        destination=url,
                        success=True,
                        records_written=1,
                    )
                elif response.status_code == 429:
                    # Rate limited - back off
                    wait_time = self._retry_delay * (2**attempt)
                    logger.warning("Rate limited, backing off", wait=wait_time)
                    await asyncio.sleep(wait_time)
                    continue
                elif response.status_code >= 500:
                    # Server error - retry
                    wait_time = self._retry_delay * (2**attempt)
                    logger.warning("Server error, retrying", status=response.status_code, attempt=attempt)
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # Client error - don't retry
                    return LoadResult(
                        document_id=document_id,
                        destination=url,
                        success=False,
                        error=f"HTTP {response.status_code}: {response.text[:200]}",
                    )

            except ImportError:
                return LoadResult(
                    document_id=document_id,
                    destination=url,
                    success=False,
                    error="httpx not installed",
                )
            except Exception as e:
                if attempt == self._max_retries - 1:
                    logger.error("API load failed after retries", document_id=document_id, error=str(e))
                    return LoadResult(
                        document_id=document_id,
                        destination=url,
                        success=False,
                        error=str(e),
                    )
                await asyncio.sleep(self._retry_delay * (2**attempt))

        return LoadResult(document_id=document_id, destination=url, success=False, error="Max retries exceeded")

    async def load_batch(self, records: list[dict[str, Any]], document_ids: list[str]) -> list[LoadResult]:
        """Send multiple records to the API."""
        results = []
        for data, doc_id in zip(records, document_ids):
            result = await self.load(data, doc_id)
            results.append(result)
        return results

    async def health_check(self) -> bool:
        """Check API availability via a HEAD request."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.head(self._base_url, headers=self._headers)
            return response.status_code < 500
        except Exception:
            return False

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        import time

        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._rate_limit_interval:
            await asyncio.sleep(self._rate_limit_interval - elapsed)
        self._last_request_time = time.time()
