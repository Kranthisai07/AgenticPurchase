import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class LoggingMiddleware(BaseHTTPMiddleware):
    """Emit a structured log line for every HTTP request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()
        request_id = getattr(request.state, "request_id", "unknown")

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        logger = structlog.get_logger("http")
        logger.info("http.request")

        response = await call_next(request)

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "http.response",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
