from __future__ import annotations

import pytest

from ..libs.schemas.models import ProductHypothesis
from ..apps.agent2_intent import main as agent2


@pytest.fixture
def hypo_bottle():
    return ProductHypothesis(
        label="bottle",
        display_name="water bottle",
        brand="Nike",
        color="blue",
        category="drinkware",
    )


@pytest.fixture
def hypo_object():
    return ProductHypothesis(label="object")


class TestProposeOptions:
    def test_supported_item_returns_options(self, hypo_bottle):
        payload = agent2.propose_options(hypo_bottle)
        assert "prompt" in payload
        assert len(payload["options"]) == 3
        assert payload["options"][0]["label"].startswith("Same")

    def test_unsupported_returns_retry_prompt(self, hypo_object):
        payload = agent2.propose_options(hypo_object)
        assert payload["options"] == []
        assert "try another" in payload["prompt"].lower()


class TestConfirmIntent:
    @pytest.mark.asyncio
    async def test_same_item_choice(self, hypo_bottle):
        pi = await agent2.confirm_intent(hypo_bottle, "same water bottle qty 2")
        assert pi.item_name == "water bottle"
        assert pi.quantity == 2
        assert pi.brand == "Nike"

    @pytest.mark.asyncio
    async def test_different_color_extracts_hint(self, hypo_bottle):
        pi = await agent2.confirm_intent(hypo_bottle, "different color red budget $40")
        assert pi.color == "red"
        assert pi.budget_usd == 40.0

    @pytest.mark.asyncio
    async def test_different_brand_drops_brand(self, hypo_bottle):
        pi = await agent2.confirm_intent(hypo_bottle, "different brand please")
        assert pi.brand is None

    @pytest.mark.asyncio
    async def test_object_fallback_parses_color_and_budget(self, hypo_object):
        pi = await agent2.confirm_intent(hypo_object, "need a blue pen under $15")
        assert pi.color == "blue"
        assert pi.budget_usd == 15.0
        assert pi.quantity == 1

    @pytest.mark.asyncio
    async def test_qty_wording_defaults(self, hypo_bottle):
        pi = await agent2.confirm_intent(hypo_bottle, "same product")
        assert pi.quantity == 1


class TestExtractors:
    def test_extract_budget(self):
        assert agent2._extract_budget("budget $25") == 25.0
        assert agent2._extract_budget("under 30 dollars") == 30.0
        assert agent2._extract_budget("no budget") is None

    def test_extract_qty(self):
        assert agent2._extract_qty("need 3 units") == 3
        assert agent2._extract_qty("qty2") == 2
        assert agent2._extract_qty("just want one") == 1
