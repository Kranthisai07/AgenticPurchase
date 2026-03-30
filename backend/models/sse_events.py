from enum import Enum
from typing import Any

from pydantic import BaseModel

from backend.models.offer import RankedOffer
from backend.models.trust import TrustLevel


class SSEEventType(str, Enum):
    SESSION_READY = "session_ready"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETE = "agent_complete"
    AGENT_FAILED = "agent_failed"
    CLARIFICATION_NEEDED = "clarification_needed"
    OFFERS_READY = "offers_ready"
    TRUST_SCORED = "trust_scored"
    CHECKOUT_READY = "checkout_ready"
    SAGA_COMPLETE = "saga_complete"
    SAGA_FAILED = "saga_failed"


class SSEEvent(BaseModel):
    event: SSEEventType
    data: Any

    def to_sse_string(self) -> str:
        import json
        data_str = json.dumps(self.data if isinstance(self.data, dict) else self.data.model_dump() if hasattr(self.data, "model_dump") else self.data)
        return f"event: {self.event.value}\ndata: {data_str}\n\n"


# ── Typed payloads ────────────────────────────────────────────────────────────

class SessionReadyPayload(BaseModel):
    session_id: str
    saga_id: str


class AgentStartedPayload(BaseModel):
    agent: str
    message: str


class AgentCompletePayload(BaseModel):
    agent: str
    duration_ms: int


class AgentFailedPayload(BaseModel):
    agent: str
    error: str


class ClarificationNeededPayload(BaseModel):
    questions: list[str]
    partial_intent: dict


class OffersReadyPayload(BaseModel):
    offers: list[RankedOffer]
    ranking_explanation: str


class TrustScoredPayload(BaseModel):
    offer_id: str
    trust_level: TrustLevel
    explanation: str


class CheckoutReadyPayload(BaseModel):
    client_secret: str
    amount: float
    currency: str


class SagaCompletePayload(BaseModel):
    receipt_id: str
    summary: str


class SagaFailedPayload(BaseModel):
    reason: str
    user_message: str
    retry_allowed: bool
