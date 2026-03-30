"""
Integration test: full happy-path pipeline.
Mocks all external APIs. Tests the complete agent chain.
"""
import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agents.bus import AgentBus
from backend.agents.checkout.agent import CheckoutAgent
from backend.agents.intent.agent import IntentAgent
from backend.agents.ranking.agent import RankingAgent
from backend.agents.sourcing.agent import SourcingAgent
from backend.agents.trust.agent import TrustAgent
from backend.agents.vision.agent import VisionAgent
from backend.core.injection_guard import InjectionResult
from backend.models.agent_messages import AgentType


@pytest.fixture
def mock_injection_guard():
    guard = AsyncMock()
    # Default: safe (not injection)
    guard.check = AsyncMock(return_value=InjectionResult(
        is_injection=False,
        confidence=0.0,
        reason="safe",
        stage="static",
    ))
    return guard


@pytest.fixture
def mock_llm_vision():
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=json.dumps({
        "product_description": "blue ceramic coffee mug",
        "detected_attributes": {"category": "kitchenware", "color": "blue"},
        "confidence": 0.92,
    })))
    return llm


@pytest.fixture
def mock_llm_intent():
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=json.dumps({
        "primary_query": "blue ceramic coffee mug",
        "category": "kitchenware",
        "price_min": None,
        "price_max": 80.0,
        "condition": "new",
        "urgency": "any",
        "gift_wrapping": False,
        "quantity": 1,
        "needs_clarification": False,
        "clarification_questions": [],
    })))
    return llm


@pytest.fixture
def mock_llm_ranking():
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(
        content="Do you prefer cheaper or better rated?"
    ))
    return llm


@pytest.fixture
def full_bus(
    mock_llm_vision,
    mock_llm_intent,
    mock_llm_ranking,
    mock_ebay_client,
    mock_serpapi_client,
    mock_stripe_client,
    mock_redis,
    mock_injection_guard,
):
    bus = AgentBus()

    # Vision
    vision = VisionAgent.__new__(VisionAgent)
    vision.llm = mock_llm_vision
    vision.tools = []
    import structlog
    vision._logger = structlog.get_logger("vision")
    bus.register(vision)

    # Intent
    intent = IntentAgent.__new__(IntentAgent)
    intent.llm = mock_llm_intent
    intent.tools = []
    intent._logger = structlog.get_logger("intent")
    intent._injection_guard = mock_injection_guard
    bus.register(intent)

    # Sourcing
    sourcing = SourcingAgent(
        ebay_client=mock_ebay_client,
        serpapi_client=mock_serpapi_client,
    )
    bus.register(sourcing)

    # Trust
    trust = TrustAgent(ebay_client=mock_ebay_client)
    bus.register(trust)

    # Ranking
    ranking = RankingAgent.__new__(RankingAgent)
    ranking.llm = mock_llm_ranking
    ranking.tools = []
    ranking._logger = structlog.get_logger("ranking")
    bus.register(ranking)

    # Checkout
    checkout = CheckoutAgent.__new__(CheckoutAgent)
    checkout._stripe = mock_stripe_client
    checkout._redis = mock_redis
    checkout.llm = None
    checkout.tools = []
    checkout._logger = structlog.get_logger("checkout")
    from backend.core.config import get_settings
    checkout._settings = get_settings()
    bus.register(checkout)

    return bus


@pytest.mark.asyncio
async def test_vision_to_intent_chain(full_bus):
    from backend.models.agent_tasks import VisionTask, IntentTask
    from backend.models.agent_results import VisionSuccess, IntentSuccess

    vision_result = await full_bus.dispatch(
        AgentType.VISION,
        VisionTask(user_text="blue ceramic mug"),
        saga_id="test-saga-1",
    )
    assert vision_result.status == "success"
    assert isinstance(vision_result.result, VisionSuccess)

    intent_result = await full_bus.dispatch(
        AgentType.INTENT,
        IntentTask(product_description=vision_result.result.product_description),
        saga_id="test-saga-1",
    )
    assert intent_result.status == "success"
    assert isinstance(intent_result.result, IntentSuccess)
    assert intent_result.result.parsed_intent.primary_query != ""


@pytest.mark.asyncio
async def test_parallel_sourcing(full_bus):
    from backend.models.agent_tasks import SourcingTask
    from backend.models.intent import ParsedIntent
    from backend.models.agent_results import SourcingSuccess

    intent = ParsedIntent(primary_query="blue ceramic mug", category="kitchenware")

    results = await full_bus.dispatch_parallel(
        [
            (AgentType.SOURCING, SourcingTask(source="ebay", parsed_intent=intent)),
            (AgentType.SOURCING, SourcingTask(source="serpapi", parsed_intent=intent)),
        ],
        saga_id="test-saga-2",
    )

    assert len(results) == 2
    successes = [r for r in results if r.status == "success"]
    assert len(successes) >= 1  # at least one source succeeded


@pytest.mark.asyncio
async def test_trust_then_ranking_chain(full_bus, mock_redis):
    from backend.models.agent_tasks import SourcingTask, TrustTask, RankingTask
    from backend.models.intent import ParsedIntent
    from backend.models.agent_results import SourcingSuccess, TrustSuccess, RankingSuccess

    intent = ParsedIntent(primary_query="blue ceramic mug", category="kitchenware")

    sourcing_result = await full_bus.dispatch(
        AgentType.SOURCING,
        SourcingTask(source="ebay", parsed_intent=intent),
        saga_id="test-saga-3",
    )
    assert isinstance(sourcing_result.result, SourcingSuccess)

    trust_result = await full_bus.dispatch(
        AgentType.TRUST,
        TrustTask(offers=sourcing_result.result.offers, source="ebay"),
        saga_id="test-saga-3",
    )
    assert isinstance(trust_result.result, TrustSuccess)

    ranking_result = await full_bus.dispatch(
        AgentType.RANKING,
        RankingTask(
            scored_offers=trust_result.result.scored_offers,
            parsed_intent=intent,
        ),
        saga_id="test-saga-3",
    )
    assert isinstance(ranking_result.result, RankingSuccess)
    assert len(ranking_result.result.ranked_offers) >= 1
    assert ranking_result.result.ranked_offers[0].rank == 1
