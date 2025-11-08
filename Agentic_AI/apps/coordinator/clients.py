from __future__ import annotations

import os
from typing import Mapping

import httpx

from ...libs.schemas.models import (
    Offer,
    PaymentInput,
    ProductHypothesis,
    PurchaseIntent,
    Receipt,
    TrustAssessment,
)
from ..agent1_vision.main import intake_image as local_intake_image
from ..agent2_intent.main import confirm_intent as local_confirm_intent
from ..agent2_intent.main import confirm_from_choice as local_confirm_from_choice
from ..agent3_sourcing.main import offers_for_intent as local_offers_for_intent
from ..agent4_trust.main import assess as local_assess
from ..agent5_checkout.main import pay as local_pay


DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

_AGENT_VISION_URL = os.getenv("AGENT_VISION_URL")
_AGENT_INTENT_URL = os.getenv("AGENT_INTENT_URL")
_AGENT_SOURCING_URL = os.getenv("AGENT_SOURCING_URL")
_AGENT_TRUST_URL = os.getenv("AGENT_TRUST_URL")
_AGENT_CHECKOUT_URL = os.getenv("AGENT_CHECKOUT_URL")


def _merge_headers(base: Mapping[str, str] | None, extra: Mapping[str, str] | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    if base:
        merged.update(base)
    if extra:
        merged.update(extra)
    return merged


async def call_vision(
    image_filename: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> ProductHypothesis:
    if not _AGENT_VISION_URL:
        return await local_intake_image(image_filename)

    url = f"{_AGENT_VISION_URL.rstrip('/')}/intake"
    req_headers = _merge_headers({"Accept": "application/json"}, headers)
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        with open(image_filename, "rb") as data:
            files = {"image": (os.path.basename(image_filename), data, "application/octet-stream")}
            resp = await client.post(url, files=files, headers=req_headers)
    resp.raise_for_status()
    return ProductHypothesis.model_validate(resp.json())


async def call_intent_confirm(
    hypothesis: ProductHypothesis,
    *,
    user_text: str | None = None,
    choice_key: str | None = None,
    color_hint: str | None = None,
    quantity: int | None = None,
    budget_usd: float | None = None,
    headers: Mapping[str, str] | None = None,
) -> PurchaseIntent:
    if not _AGENT_INTENT_URL:
        if choice_key:
            return local_confirm_from_choice(
                hypothesis,
                choice_key,
                color_hint=color_hint,
                qty=quantity,
                budget=budget_usd,
            )
        return await local_confirm_intent(hypothesis, user_text=user_text)

    url = f"{_AGENT_INTENT_URL.rstrip('/')}/confirm"
    req_headers = _merge_headers({"Accept": "application/json"}, headers)
    payload = {
        "hypothesis": hypothesis.model_dump(),
        "user_text": user_text,
        "choice_key": choice_key,
        "color_hint": color_hint,
        "quantity": quantity,
        "budget_usd": budget_usd,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=req_headers)
    resp.raise_for_status()
    return PurchaseIntent.model_validate(resp.json())


async def call_sourcing(
    intent: PurchaseIntent,
    *,
    top_k: int = 5,
    headers: Mapping[str, str] | None = None,
) -> list[Offer]:
    if not _AGENT_SOURCING_URL:
        return await local_offers_for_intent(intent, top_k=top_k)

    url = f"{_AGENT_SOURCING_URL.rstrip('/')}/offers"
    req_headers = _merge_headers({"Accept": "application/json"}, headers)
    payload = {"intent": intent.model_dump(), "top_k": top_k}
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=req_headers)
    resp.raise_for_status()
    data = resp.json()
    return [Offer.model_validate(item) for item in data]


async def call_trust(
    offer: Offer,
    *,
    headers: Mapping[str, str] | None = None,
) -> TrustAssessment:
    if not _AGENT_TRUST_URL:
        return await local_assess(offer)

    url = f"{_AGENT_TRUST_URL.rstrip('/')}/assess"
    req_headers = _merge_headers({"Accept": "application/json"}, headers)
    payload = {"offer": offer.model_dump()}
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=req_headers)
    resp.raise_for_status()
    return TrustAssessment.model_validate(resp.json())


async def call_checkout(
    offer: Offer,
    payment: PaymentInput,
    *,
    idempotency_key: str,
    headers: Mapping[str, str] | None = None,
) -> Receipt:
    if not _AGENT_CHECKOUT_URL:
        return await local_pay(offer, payment, idempotency_key)

    url = f"{_AGENT_CHECKOUT_URL.rstrip('/')}/pay"
    req_headers = _merge_headers({"Accept": "application/json"}, headers)
    payload = {
        "offer": offer.model_dump(),
        "payment": payment.model_dump(),
        "idempotency_key": idempotency_key or None,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=req_headers)
    resp.raise_for_status()
    return Receipt.model_validate(resp.json())
