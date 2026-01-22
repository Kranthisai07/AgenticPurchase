from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class BBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class ProductHypothesis(BaseModel):
    label: str
    brand: Optional[str] = None
    bbox: Optional[BBox] = None
    confidence: float = 0.5
    clip_vec: Optional[List[float]] = None
    item_type: Optional[str] = None  # legacy alias for category
    category: Optional[str] = None
    display_name: Optional[str] = None
    color: Optional[str] = None


class PurchaseIntent(BaseModel):
    item_name: str
    color: Optional[str] = None
    size: Optional[str] = None
    quantity: int = 1
    budget_usd: Optional[float] = None
    brand: Optional[str] = None
    category: Optional[str] = None


class Offer(BaseModel):
    vendor: str
    title: str
    price_usd: float
    shipping_days: int
    eta_days: int
    url: str
    score: float = 0.0
    category: Optional[str] = None
    keywords: Optional[List[str]] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class TrustAssessment(BaseModel):
    vendor: str
    tls: bool
    domain_age_days: int
    has_policy_pages: bool
    risk: str  # "low" | "medium" | "high"
    happy_reviews_pct: Optional[float] = None
    accepts_returns: Optional[bool] = None
    average_refund_time_days: Optional[int] = None
    historical_issues: Optional[bool] = None
    # Optional authenticity/price fields (forward-compatible; UI/tests can ignore)
    auth_label: Optional[str] = None
    auth_score: Optional[float] = None
    auth_reasons: Optional[List[str]] = None
    price_zscore: Optional[float] = None
    weight_zscore: Optional[float] = None
    dimension_zscores: Optional[Dict[str, float]] = None
    brand_mismatch: Optional[bool] = None
    domain_mismatch: Optional[bool] = None
    vision_mismatch: Optional[bool] = None
    replica_terms: Optional[List[str]] = None


class Address(BaseModel):
    name: str
    line1: str
    line2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: str
    phone: Optional[str] = None


class PaymentMethod(BaseModel):
    brand: str
    last4: str
    expiry_month: int
    expiry_year: int


class ShippingOption(BaseModel):
    carrier: str
    service: str
    eta_business_days: int
    cost_usd: float


class CheckoutProfile(BaseModel):
    address: Address
    payment: PaymentMethod
    shipping: ShippingOption


class PaymentInput(BaseModel):
    card_number: str
    expiry_mm_yy: str
    cvv: str
    amount_usd: float


class Receipt(BaseModel):
    order_id: str
    idempotency_key: str
    amount_usd: float
    vendor: Optional[str] = None
    card_brand: Optional[str] = None
    masked_card: Optional[str] = None
