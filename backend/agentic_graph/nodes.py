from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Dict, List, Optional

from ..libs.schemas.models import Offer, PaymentInput, TrustAssessment

from .state import SagaState
from ..apps.agent1_vision.main import intake_image
from ..apps.agent2_intent.main import confirm_intent
from ..apps.agent3_sourcing.main import (
    offers_for_intent,
    offers_for_intent_fuzzy,
    offers_for_intent_strict,
)
from ..apps.agent4_trust.main import assess as assess_trust
from ..apps.agent5_checkout.main import pay as checkout_pay


def _message(stage: str, sender: str, recipient: str, content: str, **extra: object) -> Dict[str, object]:
    msg = {
        "stage": stage,
        "sender": sender,
        "recipient": recipient,
        "content": content,
        "ts": round(time.time(), 3),
    }
    for key, value in extra.items():
        if value is not None:
            msg[key] = value
    return msg


def _event(stage: str, dt: float, **extra: object) -> Dict[str, object]:
    event = {"stage": stage, "dt_s": round(dt, 4), "ok": True}
    for key, value in extra.items():
        if value is not None:
            event[key] = value
    return event


async def capture_node(state: SagaState, *_args, **_kwargs) -> Dict[str, object]:
    if not state.image_path:
        raise ValueError("capture_node requires 'image_path' on the state.")

    t0 = time.time()
    hypothesis = await intake_image(state.image_path)
    events = list(state.events)
    events.append(
        _event(
            "S1_CAPTURE",
            time.time() - t0,
            label=hypothesis.label,
            brand=hypothesis.brand,
            color=hypothesis.color,
            confidence=round(hypothesis.confidence, 3),
        )
    )
    messages = list(state.messages)
    desc = " ".join(filter(None, [hypothesis.brand, hypothesis.label])).strip() or hypothesis.label
    messages.append(
        _message(
            "S1_CAPTURE",
            sender="vision",
            recipient="intent",
            content=f"Detected {desc}",
            confidence=round(hypothesis.confidence, 3),
        )
    )
    return {"hypothesis": hypothesis, "events": events, "messages": messages}


async def intent_node(state: SagaState, *_args, **_kwargs) -> Dict[str, object]:
    if not state.hypothesis:
        raise ValueError("intent_node requires 'hypothesis' to be set.")

    t0 = time.time()
    intent = await confirm_intent(state.hypothesis, user_text=state.user_text)
    events = list(state.events)
    events.append(
        _event(
            "S2_CONFIRM",
            time.time() - t0,
            item=intent.item_name,
            color=intent.color,
            quantity=intent.quantity,
            budget=intent.budget_usd,
        )
    )
    messages = list(state.messages)
    summary = f"Need {intent.quantity}x {intent.item_name}"
    if intent.color:
        summary += f" in {intent.color}"
    messages.append(
        _message(
            "S2_CONFIRM",
            sender="intent",
            recipient="sourcing",
            content=summary,
            budget=intent.budget_usd,
        )
    )
    if state.user_text:
        messages.append(
            _message(
                "S2_CONFIRM",
                sender="intent",
                recipient="user",
                content="Understood your preference.",
            )
        )
    return {"intent": intent, "events": events, "messages": messages}


def _pick_best_offer(
    offers: List[Offer], preferred_url: Optional[str]
) -> Optional[Offer]:
    if not offers:
        return None
    if preferred_url:
        target = preferred_url.rstrip("/").lower()
        for offer in offers:
            if offer.url.rstrip("/").lower() == target:
                return offer
    return offers[0]


async def sourcing_node(state: SagaState, *_args, **_kwargs) -> Dict[str, object]:
    if not state.intent:
        raise ValueError("sourcing_node requires 'intent' to be set.")

    t0 = time.time()
    # Run strict and fuzzy strategies in parallel, then merge
    top_k = 5
    token_budgets = state.token_budgets
    token_policy = state.token_policy
    try:
        strict_task = offers_for_intent_strict(
            state.intent, top_k=top_k, token_budgets=token_budgets, token_policy=token_policy
        )
        fuzzy_task = offers_for_intent_fuzzy(
            state.intent, top_k=top_k, token_budgets=token_budgets, token_policy=token_policy
        )
        strict_offers, fuzzy_offers = await asyncio.gather(strict_task, fuzzy_task)
    except Exception:
        # Fallback to legacy single path
        strict_offers, fuzzy_offers = [], await offers_for_intent(state.intent, top_k=top_k)

    # Merge and deduplicate by URL keeping highest score
    merged: Dict[str, Offer] = {}
    def _add_all(lst: List[Offer]):
        for o in lst or []:
            key = (o.url or "").rstrip("/").lower()
            if key in merged:
                if (o.score or 0) > (merged[key].score or 0):
                    merged[key] = o
            else:
                merged[key] = o
    _add_all(strict_offers)
    _add_all(fuzzy_offers)
    offers = sorted(merged.values(), key=lambda x: x.score or 0.0, reverse=True)

    best_offer = _pick_best_offer(offers, state.preferred_offer_url)

    events = list(state.events)
    dt_total = time.time() - t0
    events.append(_event("S3_BRANCH", dt_total, strict_count=len(strict_offers or []), fuzzy_count=len(fuzzy_offers or [])))
    events.append(_event("S3_SOURCING", 0.0, offer_count=len(offers), best_vendor=getattr(best_offer, "vendor", None), best_price=getattr(best_offer, "price_usd", None)))
    messages = list(state.messages)
    if best_offer:
        messages.append(
            _message(
                "S3_SOURCING",
                sender="sourcing",
                recipient="trust",
                content=f"Top candidate {best_offer.vendor} at ${best_offer.price_usd:.2f}" if best_offer.price_usd is not None else f"Top candidate {best_offer.vendor}",
                offer_count=len(offers),
            )
        )
    else:
        messages.append(
            _message(
                "S3_SOURCING",
                sender="sourcing",
                recipient="trust",
                content="No offers matched the intent.",
            )
        )
    return {"offers": offers, "best_offer": best_offer, "events": events, "messages": messages}


async def trust_node(state: SagaState, *_args, **_kwargs) -> Dict[str, object]:
    best_offer = state.best_offer
    if not best_offer:
        events = list(state.events)
        events.append(_event("S4_TRUST", 0.0, ok=False, reason="no_offer"))
        messages = list(state.messages)
        messages.append(
            _message(
                "S4_TRUST",
                sender="trust",
                recipient="checkout",
                content="No offer available for trust evaluation.",
            )
        )
        return {"events": events, "messages": messages}

    events = list(state.events)
    messages = list(state.messages)

    t0 = time.time()
    trust = await assess_trust(best_offer)
    events.append(
        _event(
            "S4_TRUST",
            time.time() - t0,
            vendor=best_offer.vendor,
            risk=trust.risk,
        )
    )
    auth_reasons = list(trust.auth_reasons or [])
    attrs = best_offer.attributes or {}
    domain_name = (attrs.get("domain_name") or "").lower()
    domain_mismatch = bool(domain_name and not domain_name.startswith("amazon"))
    if domain_mismatch:
        auth_reasons.append("Domain is not an Amazon marketplace")
        trust.domain_mismatch = True

    hypothesis = state.hypothesis
    vision_brand = (hypothesis.brand.lower() if hypothesis and hypothesis.brand else None)
    offer_brand = (best_offer.vendor or "").lower()
    brand_mismatch = bool(vision_brand and offer_brand and vision_brand not in offer_brand)
    if brand_mismatch:
        auth_reasons.append("Vision brand differs from listing")
        trust.brand_mismatch = True

    color_mismatch = False
    if hypothesis and hypothesis.color:
        color = hypothesis.color.lower()
        blob = " ".join(filter(None, [best_offer.title, best_offer.description])).lower()
        if color and color not in blob:
            color_mismatch = True
            auth_reasons.append("Vision color not present in listing")

    trust.vision_mismatch = brand_mismatch or color_mismatch

    text_blob = " ".join(
        filter(
            None,
            [best_offer.title, best_offer.description, " ".join(best_offer.keywords or [])],
        )
    ).lower()
    replica_hits = sorted({term for term in REPLICA_TERMS if term in text_blob})
    if replica_hits:
        trust.replica_terms = replica_hits
        auth_reasons.append(f"Replica cues: {', '.join(replica_hits)}")

    if auth_reasons:
        trust.auth_reasons = auth_reasons

    if trust.replica_terms:
        trust.risk = _raise_risk(trust.risk, "high")
    if domain_mismatch:
        trust.risk = _raise_risk(trust.risk, "medium")
    if trust.vision_mismatch:
        trust.risk = _raise_risk(trust.risk, "medium")

    messages.append(
        _message(
            "S4_TRUST",
            sender="trust",
            recipient="checkout",
            content=f"{best_offer.vendor} evaluated as {trust.risk}",
            price_z=getattr(trust, "price_zscore", None),
        )
    )
    if trust.replica_terms:
        messages.append(
            _message(
                "S4_TRUST",
                sender="trust",
                recipient="sourcing",
                content="Replica cues detected",
                details=", ".join(trust.replica_terms),
            )
        )

    offers = state.offers or []
    updated_best = best_offer
    updated_trust = trust

    # Enhanced compensation: try up to K safer vendors within a price window and a latency cap
    if trust.risk in {"medium", "high"} and len(offers) > 1:
        K = int(os.getenv("S4_COMP_TOPK", "3"))
        price_window_pct = float(os.getenv("S4_COMP_PRICE_WINDOW_PCT", "10"))
        if state.comp_top_k is not None:
            try:
                K = int(state.comp_top_k)
            except Exception:
                pass
        if state.comp_price_window_pct is not None:
            try:
                price_window_pct = float(state.comp_price_window_pct)
            except Exception:
                pass
        cap_ms_env = os.getenv("S4_COMP_EXTRA_LATENCY_MS", "500")
        extra_cap_ms = int(cap_ms_env) if cap_ms_env else 500
        if state.latency_caps_ms and state.latency_caps_ms.get("S4_COMP_EXTRA_LATENCY_MS") is not None:
            extra_cap_ms = int(state.latency_caps_ms["S4_COMP_EXTRA_LATENCY_MS"])

        start_ms = time.time() * 1000.0
        baseline = best_offer.price_usd or 0.0
        attempts = 0
        for candidate in offers:
            if attempts >= K:
                break
            if candidate == best_offer:
                continue
            if (time.time() * 1000.0) - start_ms > extra_cap_ms:
                break
            # Price window check
            price_ok = True
            if baseline and candidate.price_usd is not None and price_window_pct >= 0:
                price_delta_pct = 100.0 * ((candidate.price_usd - baseline) / baseline)
                price_ok = price_delta_pct <= price_window_pct
            t1 = time.time()
            candidate_trust: TrustAssessment = await assess_trust(candidate)
            safer = candidate_trust.risk < trust.risk
            switched = bool(safer and price_ok)
            # log attempt
            events.append(
                _event(
                    "S4_COMPENSATE",
                    time.time() - t1,
                    candidate_vendor=candidate.vendor,
                    candidate_risk=candidate_trust.risk,
                    price_delta_pct=(None if baseline == 0 else round(100.0 * ((candidate.price_usd - baseline) / baseline), 2)),
                    switched=switched,
                )
            )
            attempts += 1
            if switched:
                updated_best = candidate
                updated_trust = candidate_trust
                messages.append(
                    _message(
                        "S4_TRUST",
                        sender="trust",
                        recipient="sourcing",
                        content=f"Switched to {candidate.vendor} due to lower risk",
                        candidate_risk=candidate_trust.risk,
                    )
                )
                break

    return {"best_offer": updated_best, "trust": updated_trust, "events": events, "messages": messages}


async def checkout_node(state: SagaState, *_args, **_kwargs) -> Dict[str, object]:
    events = list(state.events)
    best_offer = state.best_offer
    payment = state.payment

    messages = list(state.messages)

    if not best_offer or payment is None:
        events.append(
            _event(
                "S5_CHECKOUT",
                0.0,
                ok=False,
                reason="missing_payment_or_offer",
            )
        )
        messages.append(
            _message(
                "S5_CHECKOUT",
                sender="checkout",
                recipient="user",
                content="Checkout blocked: missing payment or offer.",
            )
        )
        return {"events": events, "messages": messages}

    payment_copy = payment.model_copy()
    payment_copy.amount_usd = best_offer.price_usd

    t0 = time.time()
    receipt = await checkout_pay(
        best_offer,
        payment_copy,
        state.idempotency_key or "",
    )
    events.append(
        _event(
            "S5_CHECKOUT",
            time.time() - t0,
            vendor=best_offer.vendor,
            amount=best_offer.price_usd,
            order_id=receipt.order_id,
        )
    )
    messages.append(
        _message(
            "S5_CHECKOUT",
            sender="checkout",
            recipient="user",
            content=f"Order confirmed with {best_offer.vendor}",
            amount=best_offer.price_usd,
            order_id=receipt.order_id,
        )
    )

    return {"receipt": receipt, "events": events, "messages": messages}
REPLICA_TERMS = [
    "replica",
    "knockoff",
    "fake",
    "dupe",
    "inspired",
    "lookalike",
    "mirror quality",
    "aaa",
    "copy",
    "compatible with",
    "style",
]


def _raise_risk(current: str, target: str) -> str:
    order = ["low", "medium", "high"]
    try:
        return order[max(order.index(current), order.index(target))]
    except ValueError:
        return target
