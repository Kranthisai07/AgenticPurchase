"""
SSEManager — thin Redis-backed SSE dispatcher.

Pushes events to the per-saga sse_queue:{saga_id} list which the
/saga/{id}/stream SSE endpoint consumes via BLPOP.

On failure (e.g. user closed the tab before the event was consumed),
the event is written to sse:pending:{saga_id}:{event_type} so the
frontend can replay it on reconnect via GET /saga/{saga_id}/pending-events.
"""
import json

from redis.asyncio import Redis

from backend.core.logging import get_logger

logger = get_logger(__name__)

# Redis key patterns (must match saga.py / pending-events route)
_QUEUE_KEY = "sse_queue:{saga_id}"
_PENDING_KEY = "sse:pending:{saga_id}:{event_type}"
_PENDING_SCAN_PATTERN = "sse:pending:{saga_id}:*"
_QUEUE_TTL = 3600
_PENDING_TTL = 600  # 10 minutes for pending replay


class SSEManager:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def emit(self, saga_id: str, event_type: str, data: dict) -> None:
        """
        Push a formatted SSE frame to the saga's stream queue.
        Raises on Redis error — callers should wrap in try/except.
        """
        raw = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        key = _QUEUE_KEY.format(saga_id=saga_id)
        await self._redis.rpush(key, raw)
        await self._redis.expire(key, _QUEUE_TTL)

    async def store_pending(
        self, saga_id: str, event_type: str, data: dict
    ) -> None:
        """
        Write an undelivered event to Redis for replay on reconnect.
        Only the most recent payload per (saga_id, event_type) is kept.
        """
        key = _PENDING_KEY.format(saga_id=saga_id, event_type=event_type)
        await self._redis.setex(key, _PENDING_TTL, json.dumps(data))  # type: ignore[arg-type]

    async def pop_pending(self, saga_id: str) -> list[dict]:
        """
        Return and delete all pending events for a saga (for reconnect replay).
        """
        pattern = _PENDING_SCAN_PATTERN.format(saga_id=saga_id)
        events: list[dict] = []
        cursor = 0
        keys_found: list[str] = []

        while True:
            cursor, batch = await self._redis.scan(cursor, match=pattern, count=100)
            keys_found.extend(batch)
            if cursor == 0:
                break

        for key in keys_found:
            raw = await self._redis.getdel(key)
            if raw:
                try:
                    payload = json.loads(raw)
                    event_type = key.split(":")[-1]
                    events.append({"event_type": event_type, "data": payload})
                except json.JSONDecodeError:
                    pass

        return events
