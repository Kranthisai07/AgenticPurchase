"""
Rate-limit singleton (H-06).

Defines the shared slowapi Limiter instance used by all rate-limited routes.
Importing this module at startup registers the limiter against the Redis
storage backend so that limits are shared across Uvicorn workers.

Usage in routes:
    from backend.api.middleware.rate_limit import limiter

    @router.post("/foo")
    @limiter.limit("5/minute")
    async def foo(request: Request, ...):   # request param required by slowapi
        ...

Usage in main.py:
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler
    from backend.api.middleware.rate_limit import limiter

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.core.config import get_settings

_settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_settings.redis_url,
    enabled=_settings.rate_limit_enabled,
)
