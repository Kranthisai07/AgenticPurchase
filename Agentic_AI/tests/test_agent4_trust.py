from __future__ import annotations

import pytest

from ..apps.agent4_trust.main import assess
from ..libs.schemas.models import Offer


def _offer(vendor: str, url: str = "http://127.0.0.1/mock/item", price: float = 10.0) -> Offer:
    return Offer(
        vendor=vendor,
        title="Sample",
        price_usd=price,
        shipping_days=3,
        eta_days=5,
        url=url,
        score=1.0,
        category="test",
        keywords=[],
        description="",
        image_url="",
    )


@pytest.mark.asyncio
async def test_known_vendor_low_risk():
    trust = await assess(_offer("Mockazon"))
    assert trust.risk == "low"
    assert trust.accepts_returns is True
    assert trust.happy_reviews_pct is not None


@pytest.mark.asyncio
async def test_vendor_with_issues_medium_or_high():
    trust = await assess(_offer("GigaDeal"))
    assert trust.risk in {"medium", "high"}
    assert trust.accepts_returns is False


@pytest.mark.asyncio
async def test_unknown_vendor_high_risk():
    trust = await assess(_offer("ShadyShop"))
    assert trust.risk == "high"
    assert trust.tls is False


@pytest.mark.asyncio
async def test_suspicious_url_high_risk():
    trust = await assess(_offer("Mockazon", url="http://mock.local/scam-deal"))
    assert trust.risk == "high"
