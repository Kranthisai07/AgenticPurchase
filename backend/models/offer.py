from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.models.common import Money
from backend.models.trust import TrustScore


class Offer(BaseModel):
    offer_id: str
    source: Literal["ebay", "serpapi"]
    title: str
    description: str | None = None
    price: Money
    url: str
    image_urls: list[str] = []
    seller_id: str
    seller_name: str
    free_shipping: bool = False
    estimated_delivery_days: int | None = None
    condition: Literal["new", "used", "refurbished", "unknown"] = "unknown"
    raw_attributes: dict[str, Any] = {}


class ScoredOffer(Offer):
    trust_score: TrustScore


class RankedOffer(ScoredOffer):
    composite_score: float = Field(ge=0.0, le=100.0)
    rank: int = Field(ge=1)
    price_score: float = Field(ge=0.0, le=25.0)
    relevance_score: float = Field(ge=0.0, le=20.0)
    rating_score: float = Field(ge=0.0, le=15.0)
    shipping_score: float = Field(ge=0.0, le=5.0)
