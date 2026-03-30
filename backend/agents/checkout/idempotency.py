"""
Checkout idempotency key generation and caching.
"""
import hashlib
import json
from typing import Any

from backend.core.redis import get_redis

IDEMPOTENCY_TTL = 86400  # 24 hours
IDEMPOTENCY_KEY_PREFIX = "checkout:idempotency:"


def generate_checkout_idempotency_key(
    saga_id: str, offer_id: str, user_id: str
) -> str:
    """Deterministic key: SHA256(saga_id:offer_id:user_id)."""
    raw = f"{saga_id}:{offer_id}:{user_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_cached_checkout_result(idempotency_key: str) -> dict[str, Any] | None:
    """Return a previously completed checkout result, if any."""
    redis_key = f"{IDEMPOTENCY_KEY_PREFIX}{idempotency_key}"
    raw = await get_redis().get(redis_key)
    if raw:
        return json.loads(raw)
    return None


async def cache_checkout_result(
    idempotency_key: str, result: dict[str, Any]
) -> None:
    """Cache a checkout result to prevent double-charges."""
    redis_key = f"{IDEMPOTENCY_KEY_PREFIX}{idempotency_key}"
    await get_redis().setex(redis_key, IDEMPOTENCY_TTL, json.dumps(result))
