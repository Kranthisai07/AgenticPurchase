"""
StripeClient — async wrapper around the Stripe Python SDK.

Design rules:
  - Raw card data NEVER passes through this service.
    Only stripe_payment_method_id (tokenised by Stripe.js on the frontend)
    is accepted here.
  - All SDK calls are sync under the hood; asyncio.to_thread() keeps them
    off the event loop so we never block other coroutines.
  - stripe.api_key is set once at import time from settings (main.py also
    sets it at startup for belt-and-suspenders safety).
"""
import asyncio
from typing import Any

import stripe

from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class StripeClient:
    def __init__(self) -> None:
        settings = get_settings()
        # Set the module-level key every time a client is constructed so
        # tests can swap it out via get_settings() mocks.
        stripe.api_key = settings.stripe_secret_key
        self._currency = settings.stripe_currency

    # ── PaymentIntents ────────────────────────────────────────────────────────

    async def create_payment_intent(
        self,
        amount_cents: int,
        currency: str,
        payment_method_id: str,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
        confirm: bool = False,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a Stripe PaymentIntent.
        Returns the raw PaymentIntent dict (includes client_secret for
        frontend confirmation via Stripe.js).
        """
        logger.info(
            "stripe.create_payment_intent",
            amount_cents=amount_cents,
            currency=currency,
            idempotency_key=idempotency_key[:16] + "...",
            confirm=confirm,
        )

        params: dict[str, Any] = {
            "amount": amount_cents,
            "currency": currency.lower(),
            "payment_method": payment_method_id,
            "confirm": confirm,
            "metadata": metadata or {},
        }
        if confirm and return_url:
            params["return_url"] = return_url

        intent = await asyncio.to_thread(
            stripe.PaymentIntent.create,
            **params,
            idempotency_key=idempotency_key,
        )

        logger.info(
            "stripe.payment_intent_created",
            intent_id=intent.id,
            status=intent.status,
        )
        return dict(intent)

    # Backwards-compatible alias used by CheckoutAgent
    async def stripe_create_payment_intent(
        self,
        amount_cents: int,
        currency: str,
        payment_method_id: str,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self.create_payment_intent(
            amount_cents=amount_cents,
            currency=currency,
            payment_method_id=payment_method_id,
            idempotency_key=idempotency_key,
            metadata=metadata,
            confirm=False,
        )

    async def confirm_payment_intent(
        self,
        intent_id: str,
        payment_method_id: str | None = None,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        """Confirm a PaymentIntent (moves status from requires_confirmation → processing)."""
        params: dict[str, Any] = {}
        if payment_method_id:
            params["payment_method"] = payment_method_id
        if return_url:
            params["return_url"] = return_url

        logger.info("stripe.confirm_payment_intent", intent_id=intent_id)
        intent = await asyncio.to_thread(
            stripe.PaymentIntent.confirm, intent_id, **params
        )
        logger.info(
            "stripe.payment_intent_confirmed",
            intent_id=intent.id,
            status=intent.status,
        )
        return dict(intent)

    async def retrieve_payment_intent(self, intent_id: str) -> dict[str, Any]:
        """Retrieve a PaymentIntent by ID."""
        intent = await asyncio.to_thread(stripe.PaymentIntent.retrieve, intent_id)
        return dict(intent)

    async def cancel_payment_intent(self, intent_id: str) -> dict[str, Any]:
        """Cancel a PaymentIntent (idempotent — already cancelled returns cleanly)."""
        logger.info("stripe.cancel_payment_intent", intent_id=intent_id)
        try:
            intent = await asyncio.to_thread(stripe.PaymentIntent.cancel, intent_id)
        except stripe.error.InvalidRequestError as exc:
            # Already cancelled — treat as success
            if "already been canceled" in str(exc).lower():
                logger.info("stripe.payment_intent_already_canceled", intent_id=intent_id)
                return {"id": intent_id, "status": "canceled"}
            raise
        return dict(intent)

    # ── Refunds ───────────────────────────────────────────────────────────────

    async def create_refund(
        self,
        payment_intent_id: str,
        amount_cents: int | None = None,
        reason: str = "requested_by_customer",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Issue a full or partial refund for a PaymentIntent.
        If amount_cents is None the full charge is refunded.
        """
        params: dict[str, Any] = {
            "payment_intent": payment_intent_id,
            "reason": reason,
            "metadata": metadata or {},
        }
        if amount_cents is not None:
            params["amount"] = amount_cents

        logger.info(
            "stripe.create_refund",
            payment_intent_id=payment_intent_id,
            amount_cents=amount_cents,
        )
        refund = await asyncio.to_thread(stripe.Refund.create, **params)
        logger.info("stripe.refund_created", refund_id=refund.id, status=refund.status)
        return dict(refund)

    # ── Payment Methods ───────────────────────────────────────────────────────

    async def retrieve_payment_method(self, pm_id: str) -> dict[str, Any]:
        """Retrieve a PaymentMethod object (type, card brand, last4, exp, etc.)."""
        pm = await asyncio.to_thread(stripe.PaymentMethod.retrieve, pm_id)
        return dict(pm)

    # ── Customers ─────────────────────────────────────────────────────────────

    async def create_customer(
        self,
        email: str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a Stripe Customer for saving payment methods across sessions."""
        customer = await asyncio.to_thread(
            stripe.Customer.create,
            email=email,
            name=name,
            metadata=metadata or {},
        )
        logger.info("stripe.customer_created", customer_id=customer.id)
        return dict(customer)

    async def retrieve_customer(self, customer_id: str) -> dict[str, Any]:
        customer = await asyncio.to_thread(stripe.Customer.retrieve, customer_id)
        return dict(customer)

    # ── Webhook event construction (test helper) ───────────────────────────────

    @staticmethod
    def construct_event(payload: bytes, sig_header: str, secret: str) -> stripe.Event:
        """
        Verify and parse a Stripe webhook event.
        Raises stripe.error.SignatureVerificationError on mismatch.
        Used by security.verify_stripe_webhook.
        """
        return stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=secret,
        )
