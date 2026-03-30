import json
from typing import Any

import redis.asyncio as aioredis

from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("redis.client.created", url=settings.redis_url)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("redis.client.closed")


# ── Saga state helpers ────────────────────────────────────────────────────────

SAGA_KEY_PREFIX = "saga:"
AGENT_RESULT_KEY_PREFIX = "agent_result:"
VENDOR_PROFILE_KEY_PREFIX = "vendor:"
CHECKOUT_VELOCITY_KEY_PREFIX = "checkout:attempts:"


async def set_saga_state(saga_id: str, state: dict[str, Any]) -> None:
    settings = get_settings()
    key = f"{SAGA_KEY_PREFIX}{saga_id}"
    await get_redis().setex(key, settings.redis_saga_ttl_seconds, json.dumps(state))


async def get_saga_state(saga_id: str) -> dict[str, Any] | None:
    key = f"{SAGA_KEY_PREFIX}{saga_id}"
    raw = await get_redis().get(key)
    return json.loads(raw) if raw else None


async def delete_saga_state(saga_id: str) -> None:
    await get_redis().delete(f"{SAGA_KEY_PREFIX}{saga_id}")


async def cache_agent_result(
    saga_id: str,
    agent_type: str,
    result: dict[str, Any],
    ttl: int = 3600,
) -> None:
    key = f"{AGENT_RESULT_KEY_PREFIX}{saga_id}:{agent_type}"
    await get_redis().setex(key, ttl, json.dumps(result))


async def get_cached_agent_result(saga_id: str, agent_type: str) -> dict[str, Any] | None:
    key = f"{AGENT_RESULT_KEY_PREFIX}{saga_id}:{agent_type}"
    raw = await get_redis().get(key)
    return json.loads(raw) if raw else None


# ── Checkout velocity ─────────────────────────────────────────────────────────

async def increment_checkout_attempts(user_id: str) -> int:
    """Increment hourly checkout counter. Returns new count."""
    key = f"{CHECKOUT_VELOCITY_KEY_PREFIX}{user_id}"
    r = get_redis()
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 3600)
    results = await pipe.execute()
    return int(results[0])


async def get_checkout_attempts(user_id: str) -> int:
    key = f"{CHECKOUT_VELOCITY_KEY_PREFIX}{user_id}"
    val = await get_redis().get(key)
    return int(val) if val else 0


# ── Vendor profile cache ──────────────────────────────────────────────────────

async def cache_vendor_profile(
    source: str,
    seller_id: str,
    profile: dict[str, Any],
    ttl: int = 86400,
) -> None:
    key = f"{VENDOR_PROFILE_KEY_PREFIX}{source}:{seller_id}"
    await get_redis().setex(key, ttl, json.dumps(profile))


async def get_cached_vendor_profile(
    source: str,
    seller_id: str,
) -> dict[str, Any] | None:
    key = f"{VENDOR_PROFILE_KEY_PREFIX}{source}:{seller_id}"
    raw = await get_redis().get(key)
    return json.loads(raw) if raw else None
