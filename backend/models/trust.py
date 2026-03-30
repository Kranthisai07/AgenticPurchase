from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class TrustLevel(str, Enum):
    LOW_RISK = "LOW_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    HIGH_RISK = "HIGH_RISK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class TrustSignals(BaseModel):
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    review_count: int | None = Field(default=None, ge=0)
    account_age_days: int | None = Field(default=None, ge=0)
    has_return_policy: bool | None = None
    fulfilled_orders: int | None = Field(default=None, ge=0)
    feedback_percentage: float | None = Field(default=None, ge=0.0, le=100.0)


class TrustScore(BaseModel):
    score: float = Field(ge=0.0, le=100.0)
    level: TrustLevel
    signals: TrustSignals
    explanation: str
    data_source: Literal["ebay_api", "insufficient"]
