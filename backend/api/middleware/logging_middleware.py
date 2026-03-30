"""
Request logging middleware.

Binds request_id, method, and path to every log line for the duration of
the request via structlog context vars.  saga_id is bound later in the
route handler when known.

Replaces the inline bind/clear calls in the legacy logging.py middleware.
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.core.logging import bind_request_context, clear_request_context, get_logger

logger = get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Emit a structured log line for every HTTP request and bind
    request-scoped context vars so all downstream log calls
    automatically include request_id, method, and path.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()

        # Use request_id set by RequestIDMiddleware if available,
        # otherwise generate a fallback so context is never empty.
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())

        # Clear any stale context from a previous request on this task,
        # then bind fresh values for this request.
        clear_request_context()
        bind_request_context(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        logger.info("http.request")

        try:
            response = await call_next(request)
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "http.response",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        except Exception as exc:
            logger.error("http.request.error", error=str(exc))
            raise
        finally:
            # Clear context so background tasks that outlive the request
            # (e.g. SSE streams) do not inherit stale request-level fields.
            clear_request_context()
