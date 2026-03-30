"""Unit tests for VisionAgent."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.agents.vision.agent import VisionAgent
from backend.models.agent_results import VisionFailure, VisionSuccess


@pytest.fixture
def vision_agent(mock_llm):
    agent = VisionAgent.__new__(VisionAgent)
    agent.llm = mock_llm
    agent.tools = []
    import structlog
    agent._logger = structlog.get_logger("test")
    return agent


@pytest.mark.asyncio
async def test_vision_text_only_success(vision_agent, mock_llm):
    mock_llm.ainvoke.return_value = MagicMock(content=json.dumps({
        "product_description": "blue ceramic coffee mug",
        "detected_attributes": {"category": "kitchenware", "color": "blue"},
        "confidence": 0.95,
    }))

    from backend.models.agent_tasks import VisionTask
    result = await vision_agent._execute(VisionTask(user_text="blue ceramic mug"))

    assert isinstance(result, VisionSuccess)
    assert result.confidence == 0.95
    assert "mug" in result.product_description


@pytest.mark.asyncio
async def test_vision_low_confidence_rejected(vision_agent, mock_llm):
    mock_llm.ainvoke.return_value = MagicMock(content=json.dumps({
        "product_description": "unclear object",
        "detected_attributes": {},
        "confidence": 0.4,
    }))

    from backend.models.agent_tasks import VisionTask
    result = await vision_agent._execute(VisionTask(user_text="blurry photo"))

    ok, reason = await vision_agent._self_evaluate(result)
    assert ok is False
    assert "confidence" in reason


@pytest.mark.asyncio
async def test_vision_no_input_returns_failure(vision_agent):
    from backend.models.agent_tasks import VisionTask
    result = await vision_agent._execute(VisionTask())

    assert isinstance(result, VisionFailure)
    assert result.error == "no_product_detected"


@pytest.mark.asyncio
async def test_vision_failure_passes_self_eval(vision_agent):
    failure = VisionFailure(error="image_unclear", suggestion="Try a clearer photo.")
    ok, reason = await vision_agent._self_evaluate(failure)
    assert ok is True


@pytest.mark.asyncio
async def test_vision_malformed_llm_response(vision_agent, mock_llm):
    mock_llm.ainvoke.return_value = MagicMock(content="not valid json")

    from backend.models.agent_tasks import VisionTask
    result = await vision_agent._execute(VisionTask(user_text="a mug"))

    assert isinstance(result, VisionFailure)
