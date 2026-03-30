"""
OrchestratorState — the LangGraph state TypedDict.
Carries all data through the graph from START to END.

PII policy (C-03):
  This state is checkpointed to Redis by LangGraph on every node
  transition.  It must NEVER contain raw PII such as shipping address
  fields, card data, or any field beyond user_id and session_id.

  Shipping addresses are persisted to Postgres via AddressRepository and
  referenced here only by address_id (a UUID string).  The full address
  is fetched from Postgres at checkout time and never written back to state.
"""
from typing import Any, AsyncGenerator, TypedDict

from backend.models.agent_results import RankingSuccess
from backend.models.intent import Message, ParsedIntent, UserPreferences
from backend.models.offer import RankedOffer, ScoredOffer
from backend.models.saga import SagaStatus
from backend.models.sse_events import SSEEvent


class OrchestratorState(TypedDict, total=False):
    # Identity
    saga_id: str
    session_id: str
    user_id: str

    # Input
    image_bytes: bytes | None
    user_text: str | None
    conversation_history: list[Message]
    user_preferences: UserPreferences

    # Vision output
    product_description: str
    vision_confidence: float
    vision_failed: bool
    vision_failure_suggestion: str
    vision_detected_attributes: dict  # VisionSuccess.detected_attributes (brand, category, ...)

    # Intent output
    parsed_intent: ParsedIntent | None
    clarification_questions: list[str]
    needs_clarification: bool
    clarification_answer: str | None  # filled in after user responds

    # Sourcing output
    all_offers: list[Any]  # list[Offer] from all sources
    sourcing_failures: list[str]  # failed source names
    all_sourcing_failed: bool

    # Trust output
    scored_offers: list[ScoredOffer]
    all_high_risk: bool
    all_insufficient: bool

    # Ranking output
    ranked_offers: list[RankedOffer]
    ranking_explanation: str
    near_tie_detected: bool
    near_tie_question: str | None
    tie_breaking_answer: str | None  # filled after user responds

    # Checkout input — address stored by reference only (C-03)
    # The full address lives in Postgres (addresses table).
    # Only the UUID is carried in state so that PII is never
    # written to the Redis checkpoint store.
    address_id: str | None    # Postgres row ID — fetch via AddressRepository at checkout

    # Checkout output
    selected_offer: RankedOffer | None
    checkout_client_secret: str | None
    receipt_id: str | None
    checkout_error: str | None
    checkout_retry_allowed: bool

    # Graph control
    saga_status: SagaStatus
    terminal_error: str | None
    retry_sourcing: bool
    retry_checkout: bool
    trust_retry_count: int  # incremented by after_trust() compensating edge

    # Schema versioning — allows forward-compatible state migration
    state_version: str  # set to "1.0" on saga creation

    # SSE emitter (injected by the API layer, not persisted)
    sse_emitter: Any | None  # Callable[[SSEEvent], Awaitable[None]]
