# apps/coordinator/saga.py
import asyncio
import time
from typing import Optional, Dict, Any, Tuple

from fastapi import HTTPException
from ...libs.utils.logging import logger
from .config import TIMEOUTS
from ...libs.schemas.models import (
    ProductHypothesis,
    PurchaseIntent,
    Offer,
    TrustAssessment,
    PaymentInput,
    Receipt,
)
from .clients import (
    call_checkout,
    call_intent_confirm,
    call_sourcing,
    call_trust,
    call_vision,
)
from .metrics import METRICS


# ----------------------
# Utilities & Helpers
# ----------------------
class SagaLog:
    """Lightweight append-only event log for the saga; returned to the caller."""
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add(self, state: str, meta: Dict[str, Any]) -> None:
        self.events.append({"ts": time.time(), "state": state, **meta})


async def with_timeout(fn, state_key: str, *args, **kwargs):
    """Run an async function with the state's configured timeout."""
    cfg = TIMEOUTS[state_key]
    return await asyncio.wait_for(fn(*args, **kwargs), timeout=cfg["timeout_s"])


async def _timeit(state: str, coro) -> Tuple[Optional[Any], float, Optional[Exception]]:
    """Measure coroutine wall time, record metrics, and return (result, dt, error)."""
    t0 = time.time()
    try:
        out = await coro
        dt = time.time() - t0
        METRICS.record(state, dt_s=dt, ok=True)
        return out, dt, None
    except Exception as e:  # noqa: BLE001 – we want to capture any error and pass up
        dt = time.time() - t0
        METRICS.record(state, dt_s=dt, ok=False)
        return None, dt, e


# ----------------------
# Saga (S1..S5)
# ----------------------
async def run_saga(
    image_filename: str,
    user_text: Optional[str],
    payment: Optional[PaymentInput],
    idempotency_key: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    preferred_offer_url: Optional[str] = None,
    auto_checkout: bool = True,
):
    """
    Orchestrates the purchase saga end-to-end:

      S1_CAPTURE  -> intake_image
      S2_CONFIRM  -> confirm_intent
      S3_SOURCING -> offers_for_intent
      S4_TRUST    -> assess (with simple compensation if risk medium/high)
      S5_CHECKOUT -> pay

    Returns a dict compatible with SagaResult.
    Raises HTTPException on failure with appropriate status codes.
    """
    if not image_filename:
        raise HTTPException(status_code=400, detail="missing_image_filename")
    if auto_checkout and payment is None:
        raise HTTPException(status_code=400, detail="missing_payment")

    log = SagaLog()
    logger.info(
        "saga_start",
        extra={
            "image": image_filename,
            "user_text": user_text,
            "idempotency_key": idempotency_key,
        },
    )

    # --- S1: Capture / Intake ---
    hypo, dt, err = await _timeit(
        "S1_CAPTURE", with_timeout(call_vision, "S1_CAPTURE", image_filename, headers=headers)
    )
    if err:
        log.add("S1_CAPTURE", {"ok": False, "error": str(err), "dt_s": round(dt, 4)})
        logger.exception("S1_CAPTURE_failed")
        raise HTTPException(status_code=504, detail=f"S1 failed: {err}")
    assert isinstance(hypo, ProductHypothesis)
    log.add(
        "S1_CAPTURE",
        {"ok": True, "brand": hypo.brand, "label": hypo.label, "dt_s": round(dt, 4)},
    )
    try:
        METRICS.log_event(
            {
                "event": "S1_CAPTURE",
                "ok": True,
                "dt_s": round(dt, 4),
                "hypothesis": hypo.model_dump(mode="json"),
                "headers": headers if headers else None,
            }
        )
    except Exception:
        pass

    # --- S2: Intent Confirmation ---
    intent, dt, err = await _timeit(
        "S2_CONFIRM",
        with_timeout(
            call_intent_confirm,
            "S2_CONFIRM",
            hypo,
            user_text=user_text,
            headers=headers,
        ),
    )
    if err:
        log.add("S2_CONFIRM", {"ok": False, "error": str(err), "dt_s": round(dt, 4)})
        logger.exception("S2_CONFIRM_failed")
        raise HTTPException(status_code=504, detail=f"S2 failed: {err}")
    assert isinstance(intent, PurchaseIntent)
    log.add(
        "S2_CONFIRM",
        {"ok": True, "intent": intent.model_dump(), "dt_s": round(dt, 4)},
    )
    try:
        METRICS.record_recognition(
            hypothesis=hypo.model_dump(mode="json"),
            intent=intent.model_dump(mode="json"),
        )
        METRICS.log_event(
            {
                "event": "S2_CONFIRM",
                "ok": True,
                "dt_s": round(dt, 4),
                "intent": intent.model_dump(mode="json"),
            }
        )
    except Exception:
        pass

    # --- S3: Product Sourcing ---
    offers, dt, err = await _timeit(
        "S3_SOURCING",
        with_timeout(call_sourcing, "S3_SOURCING", intent, headers=headers),
    )
    if err or not offers:
        msg = str(err) if err else "no offers"
        log.add("S3_SOURCING", {"ok": False, "error": msg, "dt_s": round(dt, 4)})
        logger.error("S3_SOURCING_failed: %s", msg)
        raise HTTPException(status_code=504, detail=f"S3 failed: {msg}")
    assert isinstance(offers, list) and isinstance(offers[0], Offer)
    best: Offer = offers[0]
    if preferred_offer_url:
        target = preferred_offer_url.rstrip("/").lower()
        for candidate in offers:
            if candidate.url.rstrip("/").lower() == target:
                best = candidate
                break
    log.add(
        "S3_SOURCING",
        {
            "ok": True,
            "best": best.model_dump(),
            "preferred_url": preferred_offer_url,
            "dt_s": round(dt, 4),
        },
    )
    try:
        METRICS.record_ranking([offer.model_dump(mode="json") for offer in offers])
        METRICS.log_event(
            {
                "event": "S3_SOURCING",
                "ok": True,
                "dt_s": round(dt, 4),
                "offers": [offer.model_dump(mode="json") for offer in offers],
            }
        )
    except Exception:
        pass

    # --- S4: Trust & Safety ---
    trust, dt, err = await _timeit(
        "S4_TRUST",
        with_timeout(call_trust, "S4_TRUST", best, headers=headers),
    )
    if err:
        log.add("S4_TRUST", {"ok": False, "error": str(err), "dt_s": round(dt, 4)})
        logger.exception("S4_TRUST_failed")
        raise HTTPException(status_code=504, detail=f"S4 failed: {err}")
    assert isinstance(trust, TrustAssessment)
    log.add("S4_TRUST", {"ok": True, "risk": trust.risk, "dt_s": round(dt, 4)})
    try:
        METRICS.log_event(
            {
                "event": "S4_TRUST",
                "ok": True,
                "dt_s": round(dt, 4),
                "trust": trust.model_dump(mode="json"),
            }
        )
    except Exception:
        pass

    # Simple compensation: if risky and we have a second-best option, try that
    if trust.risk in ("medium", "high") and len(offers) > 1:
        t1 = time.time()
        alt = offers[1]
        try:
            alt_trust = await call_trust(alt, headers=headers)
            if alt_trust.risk < trust.risk:
                best = alt
                trust = alt_trust
                log.add(
                    "S4_COMPENSATE",
                    {
                        "picked_next_best": True,
                        "risk": trust.risk,
                        "extra_ms": int((time.time() - t1) * 1000),
                    },
                )
        except Exception as e:
            # Non-fatal: keep original best
            log.add(
                "S4_COMPENSATE",
                {
                    "picked_next_best": False,
                    "error": f"assess_alt_failed: {e}",
                    "extra_ms": int((time.time() - t1) * 1000),
                },
            )

    # Ensure the winning offer is the first entry so downstream consumers can rely on ordering.
    if offers and offers[0] != best:
        offers = [best] + [offer for offer in offers if offer != best]

    receipt: Optional[Receipt] = None
    if auto_checkout:
        # --- S5: Checkout / Payment ---
        # Amount is driven by the selected offer; let the payment layer validate card, luhn, etc.
        assert payment is not None  # guarded above when auto_checkout is True
        payment.amount_usd = best.price_usd
        receipt, dt, err = await _timeit(
            "S5_CHECKOUT",
            with_timeout(
                call_checkout,
                "S5_CHECKOUT",
                best,
                payment,
                idempotency_key=idempotency_key or "",  # keep API stable even if None
                headers=headers,
            ),
        )
        if err:
            log.add("S5_CHECKOUT", {"ok": False, "error": str(err), "dt_s": round(dt, 4)})
            logger.exception("S5_CHECKOUT_failed")
            # 400 because card/checkout failures are usually client-side (bad card, insufficient funds, etc.)
            raise HTTPException(status_code=400, detail=f"S5 failed: {err}")
        assert isinstance(receipt, Receipt)
        log.add(
            "S5_CHECKOUT",
            {"ok": True, "receipt": receipt.model_dump(), "dt_s": round(dt, 4)},
        )
        try:
            METRICS.log_event(
                {
                    "event": "S5_CHECKOUT",
                    "ok": True,
                    "dt_s": round(dt, 4),
                    "receipt": receipt.model_dump(mode="json"),
                }
            )
        except Exception:
            pass

    # --- Done ---
    out = {
        "hypothesis": hypo,
        "intent": intent,
        "offer": best,
        "offers": offers,
        "trust": trust,
        "receipt": receipt,
        "log": log.events,
    }
    logger.info(
        "saga_complete",
        extra={
            "ok": True,
            "idempotency_key": idempotency_key,
            "auto_checkout": auto_checkout,
            "preferred_offer_url": preferred_offer_url,
        },
    )
    try:
        payload = {
            "event": "SAGA_COMPLETE",
            "ok": True,
            "hypothesis": hypo.model_dump(mode="json"),
            "intent": intent.model_dump(mode="json"),
            "offer": best.model_dump(mode="json"),
            "trust": trust.model_dump(mode="json"),
            "offers": [offer.model_dump(mode="json") for offer in offers],
            "idempotency_key": idempotency_key,
            "auto_checkout": auto_checkout,
            "preferred_offer_url": preferred_offer_url,
        }
        if receipt is not None:
            payload["receipt"] = receipt.model_dump(mode="json")
        METRICS.log_event(payload)
    except Exception:
        pass
    return out
