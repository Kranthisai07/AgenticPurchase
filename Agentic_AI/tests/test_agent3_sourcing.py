from __future__ import annotations

import pytest

from ..apps.agent3_sourcing.main import offers_for_intent, _load_catalog
from ..libs.schemas.models import PurchaseIntent


@pytest.mark.asyncio
async def test_offers_basic_drinkware(monkeypatch):
    catalog = _load_catalog()
    pi = PurchaseIntent(item_name="water bottle", category="drinkware")
    offers = await offers_for_intent(pi, top_k=3)
    assert offers
    assert offers[0].category == "drinkware"


@pytest.mark.asyncio
async def test_budget_filter(monkeypatch):
    pi = PurchaseIntent(item_name="laptop", category="electronics", budget_usd=200.0)
    offers = await offers_for_intent(pi, top_k=2)
    assert offers
    for offer in offers:
        assert offer.price_usd <= 200.0


@pytest.mark.asyncio
async def test_rewritten_url():
    pi = PurchaseIntent(item_name="pen", category="office_supplies")
    offers = await offers_for_intent(pi, top_k=1)
    assert offers[0].url.startswith("http://127.0.0.1:8000/mock/")


@pytest.mark.asyncio
async def test_tags_and_description():
    pi = PurchaseIntent(item_name="mystery", category="media")
    offer = (await offers_for_intent(pi, top_k=1))[0]
    assert offer.description
    assert offer.tags
