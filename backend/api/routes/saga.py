"""
Saga routes:
  POST /saga             → start a new purchase saga        (rate-limited, H-06)
  POST /saga/{id}/resume → resume a paused saga (clarification, selection, checkout)
  GET  /saga/{id}/stream → SSE stream for real-time agent progress (H-04)
  GET  /saga/{id}/pending-events → replay events after SSE reconnect

Auth (C-02):
  POST /saga, POST /saga/{id}/resume, GET /saga/{id}/pending-events
    → require Authorization: Bearer <jwt> header (get_current_session guard)

  GET /saga/{id}/stream
    → browser EventSource cannot send Authorization headers, so the JWT is
      accepted as a ?token= query parameter instead.  The saga_id is then
      verified against Postgres to confirm it belongs to the token's user_id
      before the SSE stream is opened (HTTP 403 otherwise).

Total saga timeout (H-03):
  Each saga background task is wrapped in asyncio.wait_for with a ceiling of
  SAGA_TOTAL_TIMEOUT seconds (default 120 s).  On expiry the client receives
  a saga_failed SSE event and the SSE stream is closed cleanly.

Input hardening (H-05):
  - user_text and user_response are capped at max_user_input_length characters.
  - resume_saga clarification responses are checked by InjectionGuard before
    being passed to the orchestrator; high-confidence injections are rejected
    with HTTP 400 and a user-friendly message.
"""
import asyncio
import json
import time
import uuid
from typing import Annotated, Any, AsyncGenerator

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.orchestrator.agent import OrchestratorAgent
from backend.api.dependencies import SessionContext, get_current_session, get_injection_guard
from backend.api.deps import get_orchestrator
from backend.api.middleware.rate_limit import limiter
from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.injection_guard import InjectionGuard
from backend.core.logging import bind_request_context, clear_request_context, get_logger
from backend.core.metrics import SAGA_COMPLETED, SAGA_DURATION, SAGA_FAILED, SAGA_STARTED
from backend.core.redis import get_saga_state
from backend.core.security import verify_session_token
from backend.models.intent import Message, UserPreferences
from backend.models.sse_events import SSEEvent
from backend.repositories.saga_repo import SagaRepository

router = APIRouter(prefix="/saga", tags=["saga"])
logger = get_logger(__name__)
settings = get_settings()

_SSE_HEARTBEAT_INTERVAL = 15  # seconds between SSE keep-alive comments
_SSE_BLPOP_TIMEOUT = 5        # seconds; short so disconnect checks fire promptly


class StartSagaResponse(BaseModel):
    saga_id: str
    session_id: str
    stream_url: str


class ResumeSagaRequest(BaseModel):
    resume_at: str  # "clarification" | "tie_breaking" | "offer_selection" | "retry_sourcing"
    user_response: str | None = None
    selected_offer_index: int | None = None
    stripe_payment_method_id: str | None = None
    shipping_address: dict | None = None


# ── Local dependency ──────────────────────────────────────────────────────────

def get_saga_repo(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SagaRepository:
    return SagaRepository(db=db)


# ── POST /saga ────────────────────────────────────────────────────────────────

@router.post("", response_model=StartSagaResponse, status_code=202)
@limiter.limit(f"{settings.rate_limit_saga_per_minute}/minute")
async def start_saga(
    request: Request,           # required by slowapi
    session: Annotated[SessionContext, Depends(get_current_session)],
    orchestrator: Annotated[OrchestratorAgent, Depends(get_orchestrator)],
    user_text: str | None = Form(None),
    image: UploadFile | None = File(None),
) -> StartSagaResponse:
    """
    Start a new purchase saga.

    user_id and session_id are taken from the verified JWT (C-02) — the client
    cannot supply or influence them.
    Returns saga_id immediately; agent progress is delivered via the SSE stream.
    Rate-limited to RATE_LIMIT_SAGA_PER_MINUTE requests per IP per minute (H-06).
    H-03: the background saga is wrapped in a total wall-clock timeout.
    H-05: user_text is capped at max_user_input_length characters.
    """
    # H-05: reject oversized text inputs before they reach any agent
    if len(user_text or "") > settings.max_user_input_length:
        raise HTTPException(
            status_code=400,
            detail=f"Input too long. Maximum {settings.max_user_input_length} characters.",
        )

    saga_id = str(uuid.uuid4())
    image_bytes = await image.read() if image else None

    # Bind saga_id so all subsequent logs in this request include it automatically
    bind_request_context(saga_id=saga_id)

    # Prometheus: count saga starts
    SAGA_STARTED.labels(session_type="user").inc()

    # Run the saga in the background — SSE client will receive events.
    # H-03: _run_saga_with_timeout enforces SAGA_TOTAL_TIMEOUT ceiling.
    asyncio.create_task(
        _run_saga_with_timeout(
            orchestrator=orchestrator,
            saga_id=saga_id,
            session_id=session.session_id,
            user_id=session.user_id,
            user_text=user_text,
            image_bytes=image_bytes,
        )
    )

    return StartSagaResponse(
        saga_id=saga_id,
        session_id=session.session_id,
        stream_url=f"/saga/{saga_id}/stream",
    )


async def _run_saga_background(
    orchestrator: OrchestratorAgent,
    saga_id: str,
    session_id: str,
    user_id: str,
    user_text: str | None,
    image_bytes: bytes | None,
) -> None:
    """Runs the saga and pushes SSE events to the saga's Redis event queue."""
    async def redis_emitter(event: SSEEvent) -> None:
        from backend.core.redis import get_redis
        r = get_redis()
        await r.rpush(
            f"sse_queue:{saga_id}",
            event.to_sse_string(),
        )
        await r.expire(f"sse_queue:{saga_id}", 3600)

    await orchestrator.start_saga(
        saga_id=saga_id,
        session_id=session_id,
        user_id=user_id,
        user_text=user_text,
        image_bytes=image_bytes,
        conversation_history=[],
        user_preferences=None,
        sse_emitter=redis_emitter,
    )

    # Saga-level token aggregation — collect per-agent counts recorded by AgentBus
    from backend.agents.bus import get_agent_bus
    tokens_by_agent = get_agent_bus().get_saga_tokens(saga_id)
    total_tokens = sum(tokens_by_agent.values())
    total_cost_usd = round(total_tokens * 0.0000065, 6) if total_tokens else None
    logger.info(
        "saga_complete",
        saga_id=saga_id,
        total_tokens=total_tokens,
        total_cost_usd=total_cost_usd,
        tokens_by_agent=tokens_by_agent,
    )

    # Signal stream completion
    from backend.core.redis import get_redis
    await get_redis().rpush(f"sse_queue:{saga_id}", "__DONE__")


async def _run_saga_with_timeout(
    orchestrator: OrchestratorAgent,
    saga_id: str,
    session_id: str,
    user_id: str,
    user_text: str | None,
    image_bytes: bytes | None,
) -> None:
    """
    H-03: Wraps _run_saga_background with a total wall-clock ceiling.

    If the saga exceeds SAGA_TOTAL_TIMEOUT seconds:
      - A saga_failed SSE event is pushed to the Redis queue.
      - The SSE stream receives __DONE__ and closes cleanly.
      - A warning is logged for observability.

    Observability: binds saga_id to context vars for the background task,
    tracks end-to-end duration, and increments SAGA_COMPLETED / SAGA_FAILED.
    """
    # Background tasks do not inherit the request context — bind explicitly.
    bind_request_context(saga_id=saga_id, context="background_saga")
    saga_start = time.monotonic()

    try:
        await asyncio.wait_for(
            _run_saga_background(
                orchestrator=orchestrator,
                saga_id=saga_id,
                session_id=session_id,
                user_id=user_id,
                user_text=user_text,
                image_bytes=image_bytes,
            ),
            timeout=settings.saga_total_timeout,
        )
        SAGA_COMPLETED.inc()
    except asyncio.TimeoutError:
        logger.warning(
            "saga.total_timeout",
            saga_id=saga_id,
            timeout_seconds=settings.saga_total_timeout,
        )
        SAGA_FAILED.labels(reason="timeout").inc()
        from backend.core.redis import get_redis
        r = get_redis()
        failed_payload = json.dumps({
            "reason": "timeout",
            "user_message": "Your request took too long. Please try again.",
            "retry_allowed": True,
        })
        failed_event = f"event: saga_failed\ndata: {failed_payload}\n\n"
        await r.rpush(f"sse_queue:{saga_id}", failed_event)
        await r.expire(f"sse_queue:{saga_id}", 3600)
        # Close the SSE stream
        await r.rpush(f"sse_queue:{saga_id}", "__DONE__")
    except Exception:
        SAGA_FAILED.labels(reason="error").inc()
        raise
    finally:
        SAGA_DURATION.observe(time.monotonic() - saga_start)
        clear_request_context()


# ── POST /saga/{id}/resume ────────────────────────────────────────────────────

@router.post("/{saga_id}/resume")
async def resume_saga(
    saga_id: str,
    body: ResumeSagaRequest,
    session: Annotated[SessionContext, Depends(get_current_session)],
    orchestrator: Annotated[OrchestratorAgent, Depends(get_orchestrator)],
    injection_guard: Annotated[InjectionGuard, Depends(get_injection_guard)],
) -> dict:
    state = await get_saga_state(saga_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Saga '{saga_id}' not found")

    # H-05: cap clarification response length before any processing
    if len(body.user_response or "") > settings.max_user_input_length:
        raise HTTPException(
            status_code=400,
            detail=f"Input too long. Maximum {settings.max_user_input_length} characters.",
        )

    # H-05: check clarification response for prompt injection
    if body.user_response:
        injection_result = await injection_guard.check(
            body.user_response,
            context="clarification_response",
        )
        if injection_result.is_injection and injection_result.confidence >= settings.injection_confidence_threshold:
            logger.warning(
                "resume_saga.injection_blocked",
                saga_id=saga_id,
                confidence=injection_result.confidence,
                reason=injection_result.reason,
            )
            raise HTTPException(
                status_code=400,
                detail="I can only help with product searches. Please describe what you're looking for.",
            )

    from backend.models.common import Address

    shipping = None
    if body.shipping_address:
        shipping = Address(**body.shipping_address)

    asyncio.create_task(
        _resume_saga_background(
            orchestrator=orchestrator,
            saga_id=saga_id,
            body=body,
            shipping_address=shipping,
        )
    )
    return {"saga_id": saga_id, "status": "resuming"}


async def _resume_saga_background(
    orchestrator: OrchestratorAgent,
    saga_id: str,
    body: ResumeSagaRequest,
    shipping_address: Any | None,
) -> None:
    async def redis_emitter(event: SSEEvent) -> None:
        from backend.core.redis import get_redis
        r = get_redis()
        await r.rpush(f"sse_queue:{saga_id}", event.to_sse_string())
        await r.expire(f"sse_queue:{saga_id}", 3600)

    await orchestrator.resume_saga(
        saga_id=saga_id,
        user_response=body.user_response or "",
        resume_at=body.resume_at,
        sse_emitter=redis_emitter,
        selected_offer_index=body.selected_offer_index,
        stripe_payment_method_id=body.stripe_payment_method_id,
        shipping_address=shipping_address,
    )
    from backend.core.redis import get_redis
    await get_redis().rpush(f"sse_queue:{saga_id}", "__DONE__")


# ── GET /saga/{id}/stream ─────────────────────────────────────────────────────

@router.get("/{saga_id}/stream")
async def stream_saga(
    saga_id: str,
    request: Request,
    token: str = Query(...),
    saga_repo: Annotated[SagaRepository, Depends(get_saga_repo)] = None,
) -> StreamingResponse:
    """
    SSE endpoint. Streams agent progress events to the frontend.

    Auth: browser EventSource cannot send Authorization headers, so the JWT is
    accepted via ?token=<jwt> query parameter.  The saga is verified to belong
    to the token's user_id before the stream is opened.

    H-04 improvements:
      - Detects client disconnects via request.is_disconnected() before each yield
      - Sends ': heartbeat' comments every 15 s so proxies/load-balancers do not
        silently drop the idle connection
      - Handles asyncio.CancelledError so server-side cleanup always runs
      - Connection: keep-alive header prevents premature closure by some clients
    """
    # ── Validate JWT from query param (EventSource cannot send headers) ────────
    try:
        claims = verify_session_token(token)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid token")

    # ── Confirm this saga belongs to the authenticated user ───────────────────
    saga = await saga_repo.get(saga_id)
    if not saga or saga.user_id != claims["sub"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    return StreamingResponse(
        _sse_generator(saga_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disables nginx response buffering
            "Connection": "keep-alive",
        },
    )


async def _sse_generator(
    saga_id: str,
    request: Request,
) -> AsyncGenerator[str, None]:
    """
    H-04: SSE generator with heartbeat and disconnect detection.

    Architecture note: saga background tasks push events to `sse_queue:{saga_id}`
    in Redis. This generator polls that queue with a short timeout (_SSE_BLPOP_TIMEOUT)
    so it can check for client disconnects and emit heartbeats without blocking
    indefinitely. The saga background task is NOT cancelled on disconnect — it
    continues running and events accumulate in Redis for replay via
    GET /saga/{saga_id}/pending-events.
    """
    from backend.core.redis import get_redis
    r = get_redis()
    key = f"sse_queue:{saga_id}"
    last_heartbeat = time.monotonic()

    try:
        # Initial heartbeat so the client knows the connection is live
        yield ": heartbeat\n\n"
        last_heartbeat = time.monotonic()

        while True:
            # ── Disconnect check ──────────────────────────────────────────
            if await request.is_disconnected():
                logger.info("sse.client_disconnected", saga_id=saga_id)
                return

            # ── Poll Redis with short timeout so disconnect checks fire ────
            result = await r.blpop(key, timeout=_SSE_BLPOP_TIMEOUT)

            if result is None:
                # Timeout — no event arrived; emit heartbeat if interval elapsed
                now = time.monotonic()
                if now - last_heartbeat >= _SSE_HEARTBEAT_INTERVAL:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now
                continue

            _, raw = result

            if raw == "__DONE__":
                # Saga completed — send the terminal frame and stop
                yield "event: stream_end\ndata: {}\n\n"
                return

            # ── Disconnect check before yielding the payload ───────────────
            if await request.is_disconnected():
                logger.info("sse.client_disconnected", saga_id=saga_id)
                return

            yield raw

            # ── Emit heartbeat if overdue after the event ──────────────────
            now = time.monotonic()
            if now - last_heartbeat >= _SSE_HEARTBEAT_INTERVAL:
                yield ": heartbeat\n\n"
                last_heartbeat = now

    except asyncio.CancelledError:
        logger.info("sse.stream_cancelled", saga_id=saga_id)

    finally:
        logger.info("sse.stream_closed", saga_id=saga_id)


# ── GET /saga/{id}/pending-events ─────────────────────────────────────────────

@router.get("/{saga_id}/pending-events")
async def get_pending_events(
    saga_id: str,
    session: Annotated[SessionContext, Depends(get_current_session)],
) -> dict:
    """
    Return and clear any SSE events stored in Redis for replay.

    Called by the frontend on SSE reconnect to recover events that were
    emitted while the connection was dropped (e.g. tab was closed during
    webhook processing).
    """
    from backend.core.sse_manager import SSEManager
    from backend.core.redis import get_redis

    manager = SSEManager(redis=get_redis())
    events = await manager.pop_pending(saga_id)
    return {"saga_id": saga_id, "events": events}
