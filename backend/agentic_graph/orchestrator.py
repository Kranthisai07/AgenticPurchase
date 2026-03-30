from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any, Dict, Optional, Union

from ..libs.schemas.models import PaymentInput

from .graph import build_graph as _build_graph_impl
from .state import SagaState


@lru_cache(maxsize=2)
def _get_graph(include_checkout: bool):
    return _build_graph_impl(include_checkout=include_checkout)


def _coerce_payment(
    payment: Optional[Union[PaymentInput, Dict[str, Any]]]
) -> Optional[PaymentInput]:
    if payment is None:
        return None
    if isinstance(payment, PaymentInput):
        return payment
    if isinstance(payment, dict):
        return PaymentInput(**payment)
    raise TypeError("payment must be a PaymentInput or dict")


async def run_saga_async(
    *,
    image_path: str,
    user_text: Optional[str] = None,
    payment: Optional[Union[PaymentInput, Dict[str, Any]]] = None,
    preferred_offer_url: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    token_budgets: Optional[Dict[str, Dict[str, int]]] = None,
    token_policy: Optional[str] = None,
    latency_caps_ms: Optional[Dict[str, int]] = None,
    comp_top_k: Optional[int] = None,
    comp_price_window_pct: Optional[float] = None,
) -> SagaState:
    """Execute the full saga including checkout."""
    initial_state = SagaState(
        image_path=image_path,
        user_text=user_text,
        payment=_coerce_payment(payment),
        preferred_offer_url=preferred_offer_url,
        idempotency_key=idempotency_key,
        token_budgets=token_budgets,
        token_policy=token_policy,
        latency_caps_ms=latency_caps_ms,
        comp_top_k=comp_top_k,
        comp_price_window_pct=comp_price_window_pct,
    )
    graph = _get_graph(include_checkout=True)
    result = await graph.ainvoke(initial_state)
    return SagaState.model_validate(result)


async def run_saga_preview_async(
    *,
    image_path: str,
    user_text: Optional[str] = None,
    preferred_offer_url: Optional[str] = None,
    token_budgets: Optional[Dict[str, Dict[str, int]]] = None,
    token_policy: Optional[str] = None,
    latency_caps_ms: Optional[Dict[str, int]] = None,
    comp_top_k: Optional[int] = None,
    comp_price_window_pct: Optional[float] = None,
) -> SagaState:
    """Run S1-S4 only (capture, intent, sourcing, trust)."""
    initial_state = SagaState(
        image_path=image_path,
        user_text=user_text,
        preferred_offer_url=preferred_offer_url,
        token_budgets=token_budgets,
        token_policy=token_policy,
        latency_caps_ms=latency_caps_ms,
        comp_top_k=comp_top_k,
        comp_price_window_pct=comp_price_window_pct,
    )
    graph = _get_graph(include_checkout=False)
    result = await graph.ainvoke(initial_state)
    return SagaState.model_validate(result)


def run_saga_sync(**kwargs) -> SagaState:
    """Synchronous wrapper for run_saga_async."""
    return asyncio.run(run_saga_async(**kwargs))


def run_saga_preview_sync(**kwargs) -> SagaState:
    """Synchronous wrapper for run_saga_preview_async."""
    return asyncio.run(run_saga_preview_async(**kwargs))


def build_graph():
    """Expose build_graph for external usage (primarily testing)."""
    return _get_graph(include_checkout=True)
