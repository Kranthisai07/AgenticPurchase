"""
BaseAPIClient — shared retry, timeout, and structured logging for all vendor clients.
"""
import asyncio
from typing import Any

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.core.exceptions import VendorAPIError

logger = structlog.get_logger(__name__)


class BaseAPIClient:
    """
    HTTP client base with:
    - Configurable timeout
    - Exponential backoff retry (3 attempts by default)
    - Structured per-request logging
    - Raises VendorAPIError on non-2xx responses

    H-01 fix: response variable is initialised to None before the retry loop.
    The status-code check is inside the `with attempt:` block so that:
      1. A non-2xx response is raised immediately and can be retried if the
         retry predicate matches (currently only transport/timeout errors retry,
         but the structure is now correct for per-attempt checking).
      2. If every attempt raises a TransportError, `response` stays None and we
         raise a clear VendorAPIError rather than an unbound NameError.
    """

    vendor: str = "unknown"
    default_timeout: float = 15.0
    max_retries: int = 3

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._build_headers(),
                timeout=self.default_timeout,
            )
        return self._client

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self._request("GET", path, params=params, headers=headers)

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self._request("POST", path, json=json, headers=headers)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        client = await self._get_client()
        bound = logger.bind(vendor=self.vendor, method=method, path=path)

        # H-01: initialise to None so that post-loop code can detect the case
        # where every retry raised a TransportError and response was never set.
        response: httpx.Response | None = None

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
            retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
            reraise=True,
        ):
            with attempt:
                bound.debug("http.request", attempt=attempt.retry_state.attempt_number)
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=headers,
                )
                # H-01: status-code check is INSIDE the with-attempt block.
                # This ensures the check happens on every attempt and that
                # `response` is always bound when we reach this point.
                if response.status_code >= 400:
                    bound.warning(
                        "http.error_response",
                        status_code=response.status_code,
                        body=response.text[:200],
                    )
                    raise VendorAPIError(
                        vendor=self.vendor,
                        status_code=response.status_code,
                        message=response.text[:200],
                    )

        # H-01: guard against the (now unlikely) case that all retries raised a
        # TransportError with reraise=True, which would have already propagated.
        # This path is a safety net so `response` is never unbound below.
        if response is None:
            raise VendorAPIError(
                vendor=self.vendor,
                status_code=0,
                message="All retry attempts failed with transport error",
            )

        bound.debug("http.response", status_code=response.status_code)
        return response.json()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
