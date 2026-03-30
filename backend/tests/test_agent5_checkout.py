from __future__ import annotations

import pytest

from ..apps.agent5_checkout.main import pay, _RECEIPT_STORE
from ..libs.schemas.models import Offer, PaymentInput


@pytest.fixture(autouse=True)
def reset_store():
    _RECEIPT_STORE.clear()
    yield
    _RECEIPT_STORE.clear()


def _offer(vendor="Mockazon", amount=25.0):
    return Offer(
        vendor=vendor,
        title="Sample",
        price_usd=amount,
        shipping_days=3,
        eta_days=5,
        url="http://127.0.0.1/mock/item",
        score=1.0,
        category="test",
        keywords=[],
        description="",
        image_url="",
    )


def _payment(card="4242424242424242", expiry="12/29"):
    return PaymentInput(
        card_number=card,
        expiry_mm_yy=expiry,
        cvv="123",
        amount_usd=25.0,
    )


@pytest.mark.asyncio
async def test_successful_payment():
    receipt = await pay(_offer(), _payment(), idem_key="")
    assert receipt.amount_usd == 25.0
    assert receipt.masked_card.endswith("4242")
    assert receipt.vendor == "Mockazon"


@pytest.mark.asyncio
async def test_idempotent_reuse():
    payment = _payment()
    offer = _offer()
    receipt1 = await pay(offer, payment, idem_key="abc")
    receipt2 = await pay(offer, payment, idem_key="abc")
    assert receipt1.order_id == receipt2.order_id


@pytest.mark.asyncio
async def test_invalid_card_rejected():
    with pytest.raises(ValueError):
        await pay(_offer(), _payment(card="123"), idem_key="")


@pytest.mark.asyncio
async def test_blacklisted_vendor():
    with pytest.raises(ValueError):
        await pay(_offer(vendor="FraudCo"), _payment(), idem_key="")


@pytest.mark.asyncio
async def test_amount_limit():
    with pytest.raises(ValueError):
        await pay(_offer(amount=6000.0), _payment(), idem_key="")


@pytest.mark.asyncio
async def test_expired_card_rejected():
    with pytest.raises(ValueError) as exc:
        await pay(_offer(), _payment(expiry="01/24"), idem_key="")
    assert "expired" in str(exc.value).lower()
