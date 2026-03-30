"""Unit tests for TrustAgent."""
import pytest

from backend.agents.trust.agent import TrustAgent
from backend.models.agent_results import TrustSuccess
from backend.models.agent_tasks import TrustTask
from backend.models.trust import TrustLevel


@pytest.fixture
def trust_agent(mock_ebay_client, mock_redis):
    return TrustAgent(ebay_client=mock_ebay_client)


@pytest.mark.asyncio
async def test_trust_scores_ebay_offers(trust_agent, sample_offer):
    task = TrustTask(offers=[sample_offer], source="ebay")
    result = await trust_agent._execute(task)

    assert isinstance(result, TrustSuccess)
    assert len(result.scored_offers) == 1
    scored = result.scored_offers[0]
    assert scored.trust_score.level in TrustLevel.__members__.values()
    assert 0 <= scored.trust_score.score <= 100


@pytest.mark.asyncio
async def test_trust_low_risk_for_excellent_seller(trust_agent, sample_offer):
    task = TrustTask(offers=[sample_offer], source="ebay")
    result = await trust_agent._execute(task)

    scored = result.scored_offers[0]
    # Seller has 500 feedback score and 99.1% → should be LOW_RISK
    assert scored.trust_score.level == TrustLevel.LOW_RISK


@pytest.mark.asyncio
async def test_trust_insufficient_data_for_new_seller(trust_agent, sample_offer, mock_ebay_client):
    mock_ebay_client.ebay_get_seller_feedback.return_value = {
        "username": "new_seller",
        "feedback_score": 2,  # < 10 → INSUFFICIENT_DATA
        "feedback_percentage": None,
    }

    task = TrustTask(offers=[sample_offer], source="ebay")
    result = await trust_agent._execute(task)

    scored = result.scored_offers[0]
    assert scored.trust_score.level == TrustLevel.INSUFFICIENT_DATA


@pytest.mark.asyncio
async def test_trust_self_eval_detects_inconsistency(trust_agent):
    from backend.models.offer import ScoredOffer
    from backend.models.trust import TrustScore, TrustSignals

    inconsistent_offer = ScoredOffer(
        offer_id="test",
        source="ebay",
        title="Test",
        price=__import__("backend.models.common", fromlist=["Money"]).Money(amount=10, currency="USD"),
        url="https://ebay.com/itm/test",
        image_urls=[],
        seller_id="s1",
        seller_name="Shop1",
        free_shipping=False,
        condition="new",
        raw_attributes={},
        trust_score=TrustScore(
            score=25.0,  # HIGH_RISK score
            level=TrustLevel.HIGH_RISK,
            signals=TrustSignals(rating=4.9, review_count=500),  # but excellent signals
            explanation="test",
            data_source="ebay_api",
        ),
    )

    result = TrustSuccess(scored_offers=[inconsistent_offer])
    ok, reason = await trust_agent._self_evaluate(result)
    assert ok is False
    assert "Inconsistent" in reason
