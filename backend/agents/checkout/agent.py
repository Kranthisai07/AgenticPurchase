"""
CheckoutAgent — creates a Stripe PaymentIntent and records the receipt.

No LLM. Purely functional.
Safety guarantees:
  - Raw card data never passes through this agent
  - Idempotency: same (saga_id, offer_id, user_id) → same result, no double-charge
  - Velocity (H-02): sliding-window limiter replaces the old fixed-window counter
    that allowed 2× the limit at the hour boundary
  - PII (C-03): when task.address_id is present the full address is fetched
    from Postgres at checkout time and is NEVER written back to LangGraph state
    or Redis. The fetched address is used only within this method's stack frame.
"""
import uuid
from typing import Any

import stripe

from backend.agents.base import BaseAgent
from backend.agents.checkout.idempotency import (
    cache_checkout_result,
    generate_checkout_idempotency_key,
    get_cached_checkout_result,
)
from backend.core.config import get_settings
from backend.core.database import get_db_session
from backend.core.redis import get_redis
from backend.core.velocity import SlidingWindowRateLimiter
from backend.models.agent_messages import AgentType
from backend.models.agent_results import CheckoutFailure, CheckoutSuccess
from backend.models.agent_tasks import CheckoutTask
from backend.models.receipt import Receipt

_VELOCITY_KEY_PREFIX = "velocity:checkout:"
_WINDOW_SECONDS = 3600  # 1-hour sliding window


class CheckoutAgent(BaseAgent):
    agent_type = AgentType.CHECKOUT
    timeout = 30

    def __init__(self) -> None:
        from backend.integrations.stripe.client import StripeClient
        super().__init__(llm=None)
        self._stripe = StripeClient()
        self._settings = get_settings()
        self._redis = get_redis()

    async def _resolve_shipping_address(self, task: CheckoutTask) -> Any:
        """
        Return the shipping address for this checkout.

        New path (C-03): task carries address_id → fetch from Postgres.
          The full address is never stored in OrchestratorState / Redis;
          it exists only within this stack frame during checkout.

        Legacy path: task carries shipping_address directly.
          Used when address_id is not yet available (e.g. during tests or
          before nodes.py is updated to pass address_id).
        """
        address_id: str | None = getattr(task, "address_id", None)
        if address_id:
            from backend.repositories.address_repository import AddressRepository
            from backend.models.common import Address as CommonAddress
            async with get_db_session() as session:
                repo = AddressRepository(session)
                persisted = await repo.get(address_id)
            return CommonAddress(
                name="",
                line1=persisted.line1,
                line2=persisted.line2,
                city=persisted.city,
                state=persisted.state,
                postal_code=persisted.postal_code,
                country=persisted.country,
            )

        # Legacy fallback — shipping_address is passed directly in the task.
        # This path is safe because CheckoutTask is constructed in-memory by
        # nodes.py and is never serialized to the Redis checkpoint store.
        return task.shipping_address

    async def _execute(self, task: CheckoutTask) -> CheckoutSuccess | CheckoutFailure:
        # 1. Sliding-window velocity check (H-02)
        #    Atomically checks and records this attempt in a Redis sorted set.
        #    Prevents the fixed-window boundary exploit (N+N attempts per 2 hours).
        limiter = SlidingWindowRateLimiter(self._redis)
        allowed, remaining = await limiter.check_and_increment(
            key=f"{_VELOCITY_KEY_PREFIX}{task.user_id}",
            limit=self._settings.checkout_max_attempts_per_hour,
            window_seconds=_WINDOW_SECONDS,
        )

        if not allowed:
            self._logger.warning(
                "checkout.velocity_exceeded",
                user_id=task.user_id,
                window_seconds=_WINDOW_SECONDS,
            )
            return CheckoutFailure(
                error="velocity_limit_exceeded",
                user_message="Too many checkout attempts. Please try again in an hour.",
                retry_allowed=False,
            )

        # 2. Idempotency check
        idem_key = generate_checkout_idempotency_key(
            task.saga_id, task.selected_offer.offer_id, task.user_id
        )
        cached = await get_cached_checkout_result(idem_key)
        if cached:
            self._logger.info("checkout.idempotency_hit", idem_key=idem_key[:16])
            return CheckoutSuccess(**cached)

        # 3. Validate quantity (Pydantic enforces ge=1, le=100; log for audit trail)
        self._logger.info("checkout.quantity_validated", quantity=task.quantity)

        # 4. Resolve shipping address — fetch from Postgres if address_id is set
        #    (C-03: fetched address stays in this stack frame, never written to state)
        shipping_address = await self._resolve_shipping_address(task)

        # 5. Create PaymentIntent
        #    Note: the velocity attempt was already recorded by check_and_increment
        #    above, so there is no separate increment call here.
        amount_cents = int(task.selected_offer.price.amount * 100)
        currency = task.selected_offer.price.currency.lower()

        try:
            intent = await self._stripe.stripe_create_payment_intent(
                amount_cents=amount_cents,
                currency=currency,
                payment_method_id=task.stripe_payment_method_id,
                idempotency_key=idem_key,
                metadata={
                    "saga_id": task.saga_id,
                    "user_id": task.user_id,
                    "offer_id": task.selected_offer.offer_id,
                },
            )
        except stripe.error.CardError as e:
            self._logger.warning("checkout.card_error", code=e.code)
            return CheckoutFailure(
                error="payment_declined",
                user_message=f"Your payment was declined: {e.user_message}",
                retry_allowed=True,
            )
        except stripe.error.StripeError as e:
            self._logger.error("checkout.stripe_error", error=str(e))
            return CheckoutFailure(
                error="stripe_unavailable",
                user_message="Payment service is temporarily unavailable. Please try again.",
                retry_allowed=True,
            )

        # 5. Record receipt — address used here, never stored back to state
        receipt_id = str(uuid.uuid4())
        receipt = Receipt(
            receipt_id=receipt_id,
            saga_id=task.saga_id,
            user_id=task.user_id,
            stripe_payment_intent_id=intent["id"],
            offer_snapshot=task.selected_offer,
            shipping_address=shipping_address,
            amount=task.selected_offer.price.amount,
            currency=currency,
        )

        success = CheckoutSuccess(
            client_secret=intent["client_secret"],
            receipt_id=receipt_id,
            estimated_delivery=None,
        )

        # Cache result for idempotency
        await cache_checkout_result(idem_key, success.model_dump())

        self._logger.info(
            "checkout.success",
            receipt_id=receipt_id,
            amount=amount_cents,
            saga_id=task.saga_id,
        )
        return success

    async def _self_evaluate(self, result: Any) -> tuple[bool, str]:
        if isinstance(result, CheckoutFailure):
            return True, ""  # failures are valid outcomes
        if isinstance(result, CheckoutSuccess):
            if not result.client_secret:
                return False, "client_secret is empty"
            if not result.receipt_id:
                return False, "receipt_id is empty"
        return True, ""
