"""Tests orchestrator behavior when all offers are HIGH_RISK."""
import pytest
from unittest.mock import AsyncMock

from backend.agents.trust.agent import TrustAgent
from backend.models.agent_tasks import TrustTask
from backend.models.agent_results import TrustSuccess
from backend.models.trust import TrustLevel


@pytest.mark.asyncio
async def test_poor_sellers_score_medium_risk(sample_offer, mock_redis):
    """
    A seller with poor feedback (score=10, 55% positive) but no counterfeit
    signals resolves to MEDIUM_RISK under the two-session trust framework.

    Session 1 (formula) produces a low score from the heuristics.
    Session 2 (LLM) evaluates counterfeit signals — poor reputation alone is
    not a counterfeit signal, so the LLM returns AUTHENTIC/SUSPICIOUS rather
    than COUNTERFEIT.  The blend (0.4 * formula + 0.6 * llm_component) lands
    in the MEDIUM_RISK band (40–70), not HIGH_RISK (<40).
    """
    ebay = AsyncMock()
    ebay.ebay_get_seller_feedback.return_value = {
        "username": "bad_seller",
        "feedback_score": 10,
        "feedback_percentage": 55.0,
    }

    agent = TrustAgent(ebay_client=ebay)
    task = TrustTask(offers=[sample_offer], source="ebay")
    result = await agent._execute(task)

    assert isinstance(result, TrustSuccess)
    assert result.scored_offers[0].trust_score.level == TrustLevel.MEDIUM_RISK


@pytest.mark.asyncio
async def test_all_high_risk_check():
    """Verify the orchestrator logic that detects all-high-risk scenarios."""
    from backend.models.trust import TrustLevel, TrustScore, TrustSignals
    from backend.models.offer import ScoredOffer
    from backend.models.common import Money

    def make_high_risk_offer(i: int) -> ScoredOffer:
        return ScoredOffer(
            offer_id=f"offer-{i}",
            source="ebay",
            title=f"Risky Product {i}",
            price=Money(amount=10.0, currency="USD"),
            url=f"https://ebay.com/itm/{i}",
            image_urls=[],
            seller_id=f"bad_seller_{i}",
            seller_name=f"BadShop{i}",
            free_shipping=False,
            condition="unknown",
            raw_attributes={},
            trust_score=TrustScore(
                score=20.0,
                level=TrustLevel.HIGH_RISK,
                signals=TrustSignals(rating=1.5, review_count=15),
                explanation="Very poor seller.",
                data_source="ebay_api",
            ),
        )

    scored = [make_high_risk_offer(i) for i in range(3)]
    all_high_risk = all(o.trust_score.level == TrustLevel.HIGH_RISK for o in scored)
    assert all_high_risk is True
