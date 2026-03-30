"""
SlidingWindowRateLimiter — Redis sorted-set based sliding window (H-02).

Replaces the fixed-window counter in backend/core/redis.py that allowed
users to double their limit at the hour boundary (N attempts just before
reset + N just after reset).

The sliding window uses a Redis sorted set where:
  - score  = Unix timestamp of the attempt
  - member = random UUID (so concurrent attempts from the same user are
             distinct entries rather than colliding updates)

All reads and writes are performed in a single atomic Lua script to prevent
TOCTOU races in high-concurrency scenarios.
"""
import time
import uuid

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


# Lua script for atomic check-and-increment.
# KEYS[1]  = the rate-limit key (e.g. "velocity:checkout:<user_id>")
# ARGV[1]  = now         (float Unix timestamp, as string)
# ARGV[2]  = window_start (float, = now - window_seconds)
# ARGV[3]  = limit       (int, max allowed in window)
# ARGV[4]  = member      (unique UUID string for this attempt)
# ARGV[5]  = window_seconds (int, used as TTL for the key)
#
# Returns: table {allowed, remaining}
#   allowed   1 if the attempt is permitted, 0 if rate-limited
#   remaining attempts left in window after this one (0 when rate-limited)

_LUA_SLIDING_WINDOW = """
local key          = KEYS[1]
local now          = tonumber(ARGV[1])
local window_start = tonumber(ARGV[2])
local limit        = tonumber(ARGV[3])
local member       = ARGV[4]
local window_secs  = tonumber(ARGV[5])

-- 1. Evict entries that fell outside the current window
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

-- 2. Count attempts still inside the window
local count = redis.call('ZCARD', key)

-- 3. Reject if already at limit
if count >= limit then
    return {0, 0}
end

-- 4. Record this attempt and refresh the key TTL
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window_secs))

return {1, limit - count - 1}
"""


class SlidingWindowRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def check_and_increment(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """
        Atomically check whether the caller is within the rate limit and, if so,
        record this attempt.

        Args:
            key:            Redis key for this limiter bucket (e.g. "velocity:checkout:<uid>")
            limit:          Maximum number of attempts allowed within the window
            window_seconds: Sliding window size in seconds

        Returns:
            (allowed, remaining) where:
              allowed   True if the attempt is permitted
              remaining Number of attempts still available after this one
                        (0 when not allowed)
        """
        now = time.time()
        window_start = now - window_seconds

        result = await self.redis.eval(
            _LUA_SLIDING_WINDOW,
            1,                    # numkeys
            key,                  # KEYS[1]
            str(now),             # ARGV[1]
            str(window_start),    # ARGV[2]
            str(limit),           # ARGV[3]
            str(uuid.uuid4()),    # ARGV[4] — unique member
            str(window_seconds),  # ARGV[5] — TTL
        )

        allowed = bool(result[0])
        remaining = int(result[1])

        if not allowed:
            logger.warning(
                "security_event",
                event_type="rate_limit_exceeded",
                saga_id="unknown",
                detail=f"limit {limit} exceeded in window {window_seconds}s",
                source_module="velocity",
            )

        return allowed, remaining

    async def get_count(self, key: str, window_seconds: int) -> int:
        """
        Return the number of attempts recorded in the current window.
        Evicts stale entries as a side-effect.
        Does not record a new attempt.
        """
        now = time.time()
        window_start = now - window_seconds
        await self.redis.zremrangebyscore(key, "-inf", window_start)
        return await self.redis.zcard(key)
