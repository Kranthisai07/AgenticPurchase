from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UserPreferences(BaseModel):
    preferred_vendors: list[str] = []
    max_budget: float | None = None
    preferred_condition: Literal["new", "used", "any"] = "any"
    past_categories: list[str] = []


class ParsedIntent(BaseModel):
    primary_query: str
    category: str
    price_min: float | None = None
    price_max: float | None = None
    preferred_vendors: list[str] = []
    excluded_vendors: list[str] = []
    condition: Literal["new", "used", "any"] = "any"
    urgency: Literal["fast_shipping", "any"] = "any"
    gift_wrapping: bool = False
    quantity: int = Field(default=1, ge=1, le=100)


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    image_url: str | None = None
    timestamp: datetime
