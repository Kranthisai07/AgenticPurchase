from typing import Literal

from pydantic import BaseModel

from backend.models.intent import ParsedIntent
from backend.models.offer import Offer, RankedOffer, ScoredOffer


# ── Vision ────────────────────────────────────────────────────────────────────

class VisionSuccess(BaseModel):
    product_description: str
    detected_attributes: dict  # category, color, material, style, brand, condition
    confidence: float


class VisionFailure(BaseModel):
    error: Literal["image_unclear", "no_product_detected", "api_timeout"]
    suggestion: str


# ── Intent ────────────────────────────────────────────────────────────────────

class IntentSuccess(BaseModel):
    parsed_intent: ParsedIntent


class IntentClarification(BaseModel):
    questions: list[str]  # max 2, specific
    partial_intent: ParsedIntent


class IntentInjectionDetected(BaseModel):
    sanitized: bool = True
    original_flagged: bool = True
    proceeds_with: str  # sanitized version


# ── Sourcing ──────────────────────────────────────────────────────────────────

class SourcingSuccess(BaseModel):
    source: str
    offers: list[Offer]
    query_used: str
    result_count: int
    is_sparse: bool = False  # True if < 3 results


class SourcingFailure(BaseModel):
    source: str
    error: Literal["api_unavailable", "zero_results", "timeout", "auth_failed"]
    suggested_query_relaxation: str | None = None


# ── Trust ─────────────────────────────────────────────────────────────────────

class TrustSuccess(BaseModel):
    scored_offers: list[ScoredOffer]
    # Session 1 + 2 enrichment — present when two-session Trust ran
    session1_batch_mean: float | None = None
    session1_batch_stdev: float | None = None
    session1_currency: str | None = None
    session2_verdicts: list[dict] | None = None   # serialised OfferVerdict list


# ── Ranking ───────────────────────────────────────────────────────────────────

class RankingSuccess(BaseModel):
    ranked_offers: list[RankedOffer]  # max 5
    ranking_explanation: str
    near_tie_detected: bool
    near_tie_question: str | None = None


# ── Checkout ──────────────────────────────────────────────────────────────────

class CheckoutSuccess(BaseModel):
    client_secret: str
    receipt_id: str
    estimated_delivery: str | None = None


class CheckoutFailure(BaseModel):
    error: Literal[
        "payment_declined",
        "stripe_unavailable",
        "offer_no_longer_available",
        "velocity_limit_exceeded",
    ]
    user_message: str
    retry_allowed: bool
