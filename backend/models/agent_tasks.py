from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.models.common import Address
from backend.models.intent import Message, ParsedIntent, UserPreferences
from backend.models.offer import RankedOffer, ScoredOffer, Offer


class VisionTask(BaseModel):
    image_bytes: bytes | None = None
    user_text: str | None = None


class IntentTask(BaseModel):
    product_description: str
    user_text: str | None = None
    conversation_history: list[Message] = []
    user_preferences: UserPreferences = Field(default_factory=UserPreferences)


class SourcingTask(BaseModel):
    source: Literal["ebay", "serpapi"]
    parsed_intent: ParsedIntent
    attempt: int = Field(default=1, ge=1, le=2)


class TrustTask(BaseModel):
    offers: list[Offer]
    source: Literal["ebay", "serpapi"]
    vision_attributes: dict[str, Any] = Field(default_factory=dict)
    product_description: str = ""


class RankingTask(BaseModel):
    scored_offers: list[ScoredOffer]
    parsed_intent: ParsedIntent
    user_preferences: UserPreferences = Field(default_factory=UserPreferences)


class CheckoutTask(BaseModel):
    saga_id: str
    selected_offer: RankedOffer
    stripe_payment_method_id: str
    shipping_address: Address
    user_id: str
    quantity: int = Field(default=1, ge=1, le=100)
