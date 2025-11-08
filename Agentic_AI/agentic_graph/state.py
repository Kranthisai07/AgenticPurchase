from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..libs.schemas.models import (
    Offer,
    PaymentInput,
    ProductHypothesis,
    PurchaseIntent,
    Receipt,
    TrustAssessment,
)


class SagaState(BaseModel):
    """Shared LangGraph state for the purchase saga."""

    # Inputs
    image_path: Optional[str] = None
    user_text: Optional[str] = None
    preferred_offer_url: Optional[str] = None
    payment: Optional[PaymentInput] = None
    idempotency_key: Optional[str] = None

    # Optional runtime policies/budgets (token + latency) for reproducibility
    # Example structure for token budgets: {"S1": {"cap": 1500}, "S3": {"cap": 2000}}
    token_budgets: Optional[Dict[str, Dict[str, int]]] = None
    token_policy: Optional[str] = None  # e.g., "warn" | "truncate" | "fallback" | "block"
    latency_caps_ms: Optional[Dict[str, int]] = None  # e.g., {"S4_COMP_EXTRA_LATENCY_MS": 500}

    # S4 per-request compensation overrides
    comp_top_k: Optional[int] = None
    comp_price_window_pct: Optional[float] = None

    # Outputs populated by the saga
    hypothesis: Optional[ProductHypothesis] = None
    intent: Optional[PurchaseIntent] = None
    offers: List[Offer] = Field(default_factory=list)
    best_offer: Optional[Offer] = None
    trust: Optional[TrustAssessment] = None
    receipt: Optional[Receipt] = None

    # Diagnostics
    events: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    def append_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Return a dict update with the new event added to the timeline."""
        updated = list(self.events)
        updated.append(event)
        return {"events": updated}
