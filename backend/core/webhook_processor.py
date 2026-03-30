"""
WebhookProcessor — handles all Stripe webhook event types off the main
request thread (invoked via FastAPI BackgroundTasks).

All SSE emission is done through SSEManager; Redis and DB access are
injected via constructor to keep this class testable.
"""
import json
import uuid
from datetime import datetime
from typing import Any

import stripe
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging import get_logger
from backend.core.metrics import CHECKOUT_FAILED, CHECKOUT_SUCCEEDED
from backend.core.redis import delete_saga_state, increment_checkout_attempts
from backend.core.sse_manager import SSEManager
from backend.integrations.supermemory.client import SupermemoryClient
from backend.models.receipt import Receipt
from backend.models.saga import SagaStatus
from backend.repositories.receipt_repo import ReceiptRepository
from backend.repositories.saga_repo import SagaRepository
from backend.repositories.webhook_repository import WebhookRepository

logger = get_logger(__name__)


class WebhookProcessor:
    def __init__(
        self,
        sse_manager: SSEManager,
        saga_repo: SagaRepository,
        receipt_repo: ReceiptRepository,
        redis: Redis,
        supermemory: SupermemoryClient,
        webhook_repo: WebhookRepository,
    ) -> None:
        self._sse = sse_manager
        self._saga_repo = saga_repo
        self._receipt_repo = receipt_repo
        self._redis = redis
        self._supermemory = supermemory
        self._webhook_repo = webhook_repo

    # ── Public entry point ────────────────────────────────────────────────────

    async def process(self, event: stripe.Event) -> None:
        """
        Dispatch to the correct handler and update the webhook event status.
        Runs inside a BackgroundTask — exceptions are logged, not re-raised,
        so the HTTP 200 already delivered to Stripe is not affected.
        """
        event_type: str = event["type"]
        event_id: str = event["id"]

        try:
            await self._dispatch(event, event_type)
            await self._webhook_repo.update_status(event_id, "completed")
        except Exception as exc:
            logger.error(
                "webhook.processing.failed",
                event_id=event_id,
                event_type=event_type,
                error=str(exc),
            )
            try:
                await self._webhook_repo.update_status(event_id, "failed")
            except Exception:
                pass

    # ── Dispatcher ────────────────────────────────────────────────────────────

    async def _dispatch(self, event: stripe.Event, event_type: str) -> None:
        if event_type == "payment_intent.succeeded":
            await self._handle_payment_succeeded(event)
        elif event_type == "payment_intent.payment_failed":
            await self._handle_payment_failed(event)
        elif event_type == "payment_intent.canceled":
            await self._handle_payment_canceled(event)
        elif event_type == "charge.dispute.created":
            await self._handle_dispute_created(event)
        elif event_type == "charge.refunded":
            await self._handle_charge_refunded(event)
        else:
            logger.debug("webhook.unhandled_event_type", event_type=event_type)

    # ── Handlers ─────────────────────────────────────────────────────────────

    async def _handle_payment_succeeded(self, event: stripe.Event) -> None:
        intent = event["data"]["object"]
        metadata: dict[str, Any] = intent.get("metadata", {})
        saga_id: str | None = metadata.get("saga_id")
        user_id: str | None = metadata.get("user_id")

        logger.info(
            "webhook.payment_intent.succeeded",
            intent_id=intent["id"],
            saga_id=saga_id,
        )

        if not saga_id:
            logger.warning("webhook.payment_succeeded.no_saga_id", intent_id=intent["id"])
            return

        # 1. Update saga status → completed
        await self._saga_repo.update_status_raw(saga_id, "completed")

        # 2. Create receipt (idempotent — CheckoutAgent may have already done it)
        receipt_id: str = await self._upsert_receipt(
            intent=intent,
            saga_id=saga_id,
            user_id=user_id or "",
        )

        # 3. Delete saga state from Redis
        await delete_saga_state(saga_id)

        # 4. Emit saga_complete SSE
        sse_data = {
            "receipt_id": receipt_id,
            "summary": f"Purchase confirmed (payment intent {intent['id']})",
            "amount": intent.get("amount_received", intent.get("amount", 0)) / 100,
            "currency": intent.get("currency", "usd").upper(),
        }
        await self._safe_emit(saga_id, "saga_complete", sse_data)

        # 5. Prometheus: confirmed checkout
        CHECKOUT_SUCCEEDED.inc()

        # 6. Store purchase in Supermemory
        if user_id:
            await self._supermemory.store_purchase(
                user_id=user_id,
                receipt_data={
                    "receipt_id": receipt_id,
                    "amount": sse_data["amount"],
                    "currency": sse_data["currency"],
                    "payment_intent_id": intent["id"],
                },
            )

    async def _handle_payment_failed(self, event: stripe.Event) -> None:
        intent = event["data"]["object"]
        metadata: dict[str, Any] = intent.get("metadata", {})
        saga_id: str | None = metadata.get("saga_id")
        user_id: str | None = metadata.get("user_id")
        last_payment_error: dict[str, Any] = intent.get("last_payment_error") or {}
        failure_message: str = last_payment_error.get("message", "Payment declined")
        failure_code: str = last_payment_error.get("code", "unknown")

        logger.warning(
            "webhook.payment_intent.payment_failed",
            intent_id=intent["id"],
            saga_id=saga_id,
            failure_message=failure_message,
        )

        if not saga_id:
            return

        # 1. Update saga status → payment_failed
        await self._saga_repo.update_status_raw(saga_id, "payment_failed")

        # 2. Increment velocity counter in Redis
        if user_id:
            await increment_checkout_attempts(user_id)

        # 3. Prometheus: failed checkout
        CHECKOUT_FAILED.labels(reason=failure_code).inc()

        # 4. Emit saga_failed SSE
        await self._safe_emit(
            saga_id,
            "saga_failed",
            {
                "reason": "payment_failed",
                "user_message": failure_message,
                "retry_allowed": True,
            },
        )

    async def _handle_payment_canceled(self, event: stripe.Event) -> None:
        intent = event["data"]["object"]
        metadata: dict[str, Any] = intent.get("metadata", {})
        saga_id: str | None = metadata.get("saga_id")

        logger.info(
            "webhook.payment_intent.canceled",
            intent_id=intent["id"],
            saga_id=saga_id,
        )

        if not saga_id:
            return

        # 1. Update saga status → canceled
        await self._saga_repo.update_status_raw(saga_id, "canceled")

        # 2. Delete saga state from Redis
        await delete_saga_state(saga_id)

        # 3. Emit saga_failed SSE (no retry for cancellation)
        await self._safe_emit(
            saga_id,
            "saga_failed",
            {
                "reason": "canceled",
                "user_message": "Your payment was canceled.",
                "retry_allowed": False,
            },
        )

    async def _handle_dispute_created(self, event: stripe.Event) -> None:
        charge = event["data"]["object"]
        payment_intent_id: str = charge.get("payment_intent", "")
        charge_id: str = charge.get("id", "")
        metadata: dict[str, Any] = charge.get("metadata", {})
        saga_id: str | None = metadata.get("saga_id")

        logger.warning(
            "webhook.charge.dispute.created",
            charge_id=charge_id,
            payment_intent_id=payment_intent_id,
            saga_id=saga_id,
        )
        # No SSE emission and no saga state change for disputes.

    async def _handle_charge_refunded(self, event: stripe.Event) -> None:
        charge = event["data"]["object"]
        metadata: dict[str, Any] = charge.get("metadata", {})
        saga_id: str | None = metadata.get("saga_id")

        amount_refunded: float = charge.get("amount_refunded", 0) / 100
        currency: str = charge.get("currency", "usd").upper()

        logger.info(
            "webhook.charge.refunded",
            charge_id=charge.get("id"),
            saga_id=saga_id,
            amount_refunded=amount_refunded,
            currency=currency,
        )

        if not saga_id:
            return

        # 1. Update saga status → refunded
        await self._saga_repo.update_status_raw(saga_id, "refunded")

        # 2. Emit refund_complete SSE
        await self._safe_emit(
            saga_id,
            "refund_complete",
            {"amount_refunded": amount_refunded, "currency": currency},
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _safe_emit(
        self, saga_id: str, event_type: str, data: dict[str, Any]
    ) -> None:
        """
        Emit an SSE event. On failure (user closed tab, etc.), persist the
        event in Redis so it can be replayed via GET /saga/{id}/pending-events.
        SSE failure must never crash webhook processing.
        """
        try:
            await self._sse.emit(saga_id, event_type, data)
        except Exception:
            logger.warning("sse.emit.failed", saga_id=saga_id, event_type=event_type)
            try:
                await self._sse.store_pending(saga_id, event_type, data)
            except Exception:
                pass

    async def _upsert_receipt(
        self,
        intent: dict[str, Any],
        saga_id: str,
        user_id: str,
    ) -> str:
        """
        Create a receipt record. If CheckoutAgent already created one for this
        PaymentIntent, the unique constraint on stripe_payment_intent_id will
        raise an IntegrityError — we catch it, look up the existing receipt,
        and compare key fields to detect discrepancies before returning.

        M-03: discrepancies (e.g. amount mismatch from currency conversion race)
        are logged as structured warnings so they are never silently swallowed.
        """
        saga = await self._saga_repo.get(saga_id)

        # Try to rebuild offer_snapshot from the saga record
        selected_offer_data: dict[str, Any] | None = None
        if saga and saga.selected_offer:
            selected_offer_data = saga.selected_offer.model_dump()

        receipt_id = str(uuid.uuid4())

        if selected_offer_data is None:
            # Offer data not available — receipt was already created by CheckoutAgent.
            # Return a sentinel ID; SSE payload uses it for client display only.
            logger.warning(
                "webhook.upsert_receipt.no_offer_data",
                saga_id=saga_id,
                intent_id=intent["id"],
            )
            return receipt_id

        from backend.models.common import Address
        from backend.models.offer import RankedOffer

        # Attempt to get shipping address from Redis saga state
        from backend.core.redis import get_saga_state
        saga_state = await get_saga_state(saga_id)
        shipping_raw: dict[str, Any] | None = (
            saga_state.get("shipping_address") if saga_state else None
        )
        shipping = (
            Address(**shipping_raw)
            if shipping_raw
            else Address(
                line1="Unknown",
                city="Unknown",
                state="Unknown",
                postal_code="00000",
                country="US",
            )
        )

        incoming_amount: float = intent.get("amount_received", intent.get("amount", 0)) / 100
        incoming_currency: str = intent.get("currency", "usd")

        receipt = Receipt(
            receipt_id=receipt_id,
            saga_id=saga_id,
            user_id=user_id or (str(saga.user_id) if saga else ""),
            stripe_payment_intent_id=intent["id"],
            offer_snapshot=RankedOffer(**selected_offer_data),
            shipping_address=shipping,
            amount=incoming_amount,
            currency=incoming_currency,
        )

        try:
            await self._receipt_repo.create(receipt)
            return receipt_id
        except IntegrityError:
            # Receipt already exists — idempotency path.
            # M-03: fetch existing and compare key fields; never swallow discrepancies.
            existing = await self._receipt_repo.get_by_saga_id(saga_id)

            if existing:
                discrepancies: dict[str, Any] = {}

                if existing.amount != incoming_amount:
                    discrepancies["amount"] = {
                        "existing": existing.amount,
                        "incoming": incoming_amount,
                    }
                if existing.currency != incoming_currency:
                    discrepancies["currency"] = {
                        "existing": existing.currency,
                        "incoming": incoming_currency,
                    }
                if existing.stripe_payment_intent_id != intent["id"]:
                    discrepancies["payment_intent_id"] = {
                        "existing": existing.stripe_payment_intent_id,
                        "incoming": intent["id"],
                    }

                if discrepancies:
                    logger.warning(
                        "receipt.discrepancy_detected",
                        saga_id=saga_id,
                        discrepancies=discrepancies,
                        existing_receipt_id=str(existing.receipt_id),
                        action="keeping_existing",
                    )
                else:
                    logger.info(
                        "receipt.duplicate_ignored",
                        saga_id=saga_id,
                        receipt_id=str(existing.receipt_id),
                    )

                return str(existing.receipt_id)

            # IntegrityError but no existing record — unexpected state, re-raise.
            logger.error(
                "receipt.integrity_error_no_existing",
                saga_id=saga_id,
                stripe_intent_id=intent["id"],
            )
            raise
