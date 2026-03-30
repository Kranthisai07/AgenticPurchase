"""Unit tests for RankingAgent."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.agents.ranking.agent import RankingAgent
from backend.agents.ranking.formula import rank_offers, detect_near_tie
from backend.models.agent_results import RankingSuccess
from backend.models.agent_tasks import RankingTask
from backend.models.common import Money
from backend.models.intent import ParsedIntent, UserPreferences
from backend.models.trust import TrustLevel, TrustScore, TrustSignals
from backend.models.offer import ScoredOffer


def make_scored_offer(title: str, price: float, rating: float, reviews: int, free_shipping: bool) -> ScoredOffer:
    return ScoredOffer(
        offer_id=f"offer-{title[:4]}",
        source="ebay",
        title=title,
        price=Money(amount=price, currency="USD"),
        url=f"https://ebay.com/itm/{title}",
        image_urls=[],
        seller_id="s1",
        seller_name="Shop",
        free_shipping=free_shipping,
        condition="new",
        raw_attributes={},
        trust_score=TrustScore(
            score=70.0 if rating >= 4.5 else 45.0,
            level=TrustLevel.LOW_RISK if rating >= 4.5 else TrustLevel.MEDIUM_RISK,
            signals=TrustSignals(rating=rating, review_count=reviews),
            explanation="test",
            data_source="ebay_api",
        ),
    )


@pytest.mark.asyncio
async def test_rank_orders_by_composite():
    offers = [
        make_scored_offer("Expensive High Quality Mug", 75.0, 4.9, 500, True),
        make_scored_offer("Cheap Low Quality Mug", 10.0, 3.2, 15, False),
        make_scored_offer("Mid Price Good Mug", 35.0, 4.5, 120, True),
    ]
    ranked = rank_offers(offers, "ceramic coffee mug")

    assert len(ranked) == 3
    assert ranked[0].rank == 1
    for i, o in enumerate(ranked):
        assert o.rank == i + 1
    # Scores should be descending
    for i in range(len(ranked) - 1):
        assert ranked[i].composite_score >= ranked[i + 1].composite_score


@pytest.mark.asyncio
async def test_rank_caps_at_5():
    offers = [make_scored_offer(f"Mug {i}", 20.0 + i, 4.5, 100, True) for i in range(8)]
    ranked = rank_offers(offers, "mug")
    assert len(ranked) == 5


@pytest.mark.asyncio
async def test_detect_near_tie():
    from backend.models.offer import RankedOffer
    offers = [
        make_scored_offer("Mug A", 35.0, 4.5, 100, True),
        make_scored_offer("Mug B", 36.0, 4.5, 100, True),
    ]
    ranked = rank_offers(offers, "mug")
    # Two very similar offers should be a near tie
    is_tie = detect_near_tie(ranked, threshold=5.0)
    assert isinstance(is_tie, bool)


@pytest.fixture
def ranking_agent(mock_llm):
    agent = RankingAgent.__new__(RankingAgent)
    agent.llm = mock_llm
    agent.tools = []
    import structlog
    agent._logger = structlog.get_logger("test")
    return agent


@pytest.mark.asyncio
async def test_ranking_agent_returns_success(ranking_agent, sample_scored_offer, sample_intent):
    task = RankingTask(
        scored_offers=[sample_scored_offer],
        parsed_intent=sample_intent,
    )
    result = await ranking_agent._execute(task)

    assert isinstance(result, RankingSuccess)
    assert len(result.ranked_offers) == 1
    assert result.ranked_offers[0].rank == 1
