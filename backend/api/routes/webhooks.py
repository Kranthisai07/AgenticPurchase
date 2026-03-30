"""
Stripe webhook handler (C-01).

Design guarantees:
  1. Raw bytes are read FIRST, before any other processing — Stripe's
     HMAC-SHA256 verification requires the exact bytes that Stripe sent.
  2. Signature is verified BEFORE any event data is trusted.  A missing
     or invalid Stripe-Signature header returns HTTP 400 immediately.
  3. Idempotency check runs immediately after verification to prevent
     double-processing of Stripe retries.
  4. The event is recorded as "processing" in Postgres before the
     background task is enqueued, so a crash after enqueue cannot
     produce an orphaned, untracked event.
  5. All event handling is offloaded to BackgroundTasks so Stripe always
     receives HTTP 200 within its 30-second timeout window.
  6. WebhookProcessor.process() is responsible for updating the event
     status to "completed" on success and "failed" on error, and for
     structured error logging — it must not re-raise so that the already-
     delivered HTTP 200 is not affected.
"""
from datetime import datetime

import stripe
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from typing import Annotated

from backend.api.deps import get_webhook_processor, get_webhook_repo
from backend.core.logging import get_logger
from backend.core.security import verify_stripe_webhook
from backend.core.webhook_processor import WebhookProcessor
from backend.models.webhook import WebhookEvent
from backend.repositories.webhook_repository import WebhookRepository

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = get_logger(__name__)


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    webhook_repo: Annotated[WebhookRepository, Depends(get_webhook_repo)],
    webhook_processor: Annotated[WebhookProcessor, Depends(get_webhook_processor)],
) -> dict:
    """
    Handle Stripe webhook events.

    Responds immediately with HTTP 200; all processing happens in a
    BackgroundTask so Stripe's 30-second timeout is never exceeded.
    """
    # ── 1. Read raw bytes FIRST (required for HMAC verification) ─────────────
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # ── 2. Verify HMAC signature BEFORE trusting any event data ──────────────
    try:
        event: stripe.Event = verify_stripe_webhook(payload, sig_header)
    except ValueError as e:
        logger.warning("stripe.webhook.invalid_signature", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    event_id: str = event["id"]
    event_type: str = event["type"]

    logger.info(
        "stripe.webhook.received",
        event_type=event_type,
        event_id=event_id,
    )

    # ── 3. Idempotency check immediately after verification ───────────────────
    already_processed = await webhook_repo.exists(event_id)
    if already_processed:
        logger.info("stripe.webhook.duplicate", event_id=event_id)
        return {"received": True}

    # ── 4. Record the event as "processing" before dispatching ───────────────
    intent = event.get("data", {}).get("object", {})
    saga_id: str | None = (intent.get("metadata") or {}).get("saga_id")

    await webhook_repo.create(
        WebhookEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            saga_id=saga_id,
            status="processing",
            created_at=datetime.utcnow(),
        )
    )

    # ── 5. Process in background — return 200 immediately ────────────────────
    # WebhookProcessor.process() handles:
    #   6. On completion  → updates webhook status to "completed"
    #   7. On exception   → updates webhook status to "failed", logs
    #                        structured error with event_id and saga_id,
    #                        does NOT re-raise (Stripe will retry on non-200)
    background_tasks.add_task(webhook_processor.process, event)

    return {"received": True}
