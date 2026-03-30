"""
Shared pytest fixtures: mock agents, mock tool clients, test DB, Redis.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.models.common import Address, Money
from backend.models.intent import ParsedIntent, UserPreferences
from backend.models.offer import Offer, ScoredOffer, RankedOffer
from backend.models.trust import TrustLevel, TrustScore, TrustSignals


# ── Model fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def sample_address() -> Address:
    return Address(
        name="Test User",
        line1="123 Main St",
        city="San Francisco",
        state="CA",
        postal_code="94102",
        country="US",
    )


@pytest.fixture
def sample_money() -> Money:
    return Money(amount=49.99, currency="USD")


@pytest.fixture
def sample_intent() -> ParsedIntent:
    return ParsedIntent(
        primary_query="blue ceramic coffee mug",
        category="kitchenware",
        price_min=10.0,
        price_max=80.0,
        condition="new",
    )


@pytest.fixture
def sample_offer(sample_money) -> Offer:
    return Offer(
        offer_id=str(uuid4()),
        source="ebay",
        title="Handmade Blue Ceramic Coffee Mug",
        description="A beautiful blue mug",
        price=sample_money,
        url="https://ebay.com/itm/123",
        image_urls=["https://example.com/mug.jpg"],
        seller_id="shop_123",
        seller_name="CeramicsStudio",
        free_shipping=True,
        estimated_delivery_days=5,
        condition="new",
    )


@pytest.fixture
def sample_trust_score() -> TrustScore:
    return TrustScore(
        score=82.5,
        level=TrustLevel.LOW_RISK,
        signals=TrustSignals(
            rating=4.8,
            review_count=320,
            account_age_days=730,
            has_return_policy=True,
            feedback_percentage=98.5,
        ),
        explanation="Trusted seller (4.8★, 320 reviews, 98.5% positive feedback).",
        data_source="ebay_api",
    )


@pytest.fixture
def sample_scored_offer(sample_offer, sample_trust_score) -> ScoredOffer:
    return ScoredOffer(**sample_offer.model_dump(), trust_score=sample_trust_score)


@pytest.fixture
def sample_ranked_offer(sample_scored_offer) -> RankedOffer:
    return RankedOffer(
        **sample_scored_offer.model_dump(),
        composite_score=78.4,
        rank=1,
        price_score=18.5,
        relevance_score=16.0,
        rating_score=14.4,
        shipping_score=5.0,
    )


# ── Mock LLM fixture ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="{}"))
    return llm


# ── Mock eBay client ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_ebay_client():
    client = AsyncMock()
    client.ebay_search = AsyncMock(return_value=[
        {
            "itemId": "ebay-001",
            "title": "Blue Coffee Mug",
            "price": {"value": "35.00", "currency": "USD"},
            "condition": "NEW",
            "itemWebUrl": "https://ebay.com/item/1",
            "image": {"imageUrl": "https://example.com/ebay.jpg"},
            "seller": {"username": "seller123", "feedbackScore": 500, "positiveFeedbackPercent": "99.1"},
            "shippingOptions": [{"shippingCost": {"value": "0.00"}}],
        }
    ])
    client.ebay_get_seller_feedback = AsyncMock(return_value={
        "username": "seller123",
        "feedback_score": 500,
        "feedback_percentage": 99.1,
    })
    return client


# ── Mock SerpApi client ────────────────────────────────────────────────────────

@pytest.fixture
def mock_serpapi_client():
    client = AsyncMock()
    client.google_shopping_search = AsyncMock(return_value=[
        {
            "title": "Ceramic Blue Mug",
            "extracted_price": 29.99,
            "source": "Amazon",
            "link": "https://amazon.com/item/1",
            "thumbnail": "https://example.com/amazon.jpg",
            "rating": 4.5,
            "reviews": 1200,
        }
    ])
    return client


# ── Mock Stripe client ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_stripe_client():
    client = AsyncMock()
    client.stripe_create_payment_intent = AsyncMock(return_value={
        "id": "pi_test_123",
        "client_secret": "pi_test_123_secret_abc",
        "status": "requires_confirmation",
    })
    return client


# ── Mock Redis ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.pipeline = MagicMock(return_value=AsyncMock(
        incr=AsyncMock(),
        expire=AsyncMock(),
        execute=AsyncMock(return_value=[1, True]),
    ))
    monkeypatch.setattr("backend.core.redis.get_redis", lambda: redis)
    monkeypatch.setattr("backend.agents.checkout.idempotency.get_redis", lambda: redis)
    return redis
