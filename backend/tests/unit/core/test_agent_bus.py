"""Unit tests for AgentBus dispatch and dispatch_parallel."""
import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from backend.agents.bus import AgentBus
from backend.models.agent_messages import AgentResult, AgentType
from backend.models.agent_results import VisionSuccess


def make_mock_agent(agent_type: AgentType, result_payload, status: str = "success"):
    agent = MagicMock()
    agent.agent_type = agent_type
    agent.run = AsyncMock(return_value=AgentResult(
        message_id="msg-1",
        saga_id="saga-1",
        agent_type=agent_type,
        status=status,
        result=result_payload,
        completed_at=datetime.utcnow(),
        duration_ms=100,
    ))
    return agent


@pytest.mark.asyncio
async def test_dispatch_calls_correct_agent():
    bus = AgentBus()
    vision_payload = VisionSuccess(
        product_description="blue mug",
        detected_attributes={},
        confidence=0.9,
    )
    mock_vision = make_mock_agent(AgentType.VISION, vision_payload)
    bus.register(mock_vision)

    from backend.models.agent_tasks import VisionTask
    result = await bus.dispatch(AgentType.VISION, VisionTask(user_text="mug"), saga_id="s1")

    assert result.status == "success"
    assert result.agent_type == AgentType.VISION
    mock_vision.run.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_parallel_returns_all_results():
    bus = AgentBus()

    vision_mock = make_mock_agent(AgentType.VISION, "vision_result")
    intent_mock = make_mock_agent(AgentType.INTENT, "intent_result")
    bus.register(vision_mock)
    bus.register(intent_mock)

    from backend.models.agent_tasks import VisionTask, IntentTask
    from backend.models.intent import ParsedIntent
    results = await bus.dispatch_parallel(
        [
            (AgentType.VISION, VisionTask(user_text="mug")),
            (AgentType.INTENT, IntentTask(product_description="mug")),
        ],
        saga_id="s1",
    )

    assert len(results) == 2
    assert {r.agent_type for r in results} == {AgentType.VISION, AgentType.INTENT}


@pytest.mark.asyncio
async def test_dispatch_unregistered_agent_raises():
    bus = AgentBus()
    from backend.core.exceptions import AgentBusError
    from backend.models.agent_tasks import VisionTask

    with pytest.raises(AgentBusError):
        await bus.dispatch(AgentType.VISION, VisionTask(), saga_id="s1")


@pytest.mark.asyncio
async def test_dispatch_parallel_isolates_failures():
    bus = AgentBus()

    working_mock = make_mock_agent(AgentType.VISION, "ok")
    failing_mock = MagicMock()
    failing_mock.agent_type = AgentType.INTENT
    failing_mock.run = AsyncMock(side_effect=RuntimeError("crash"))

    bus.register(working_mock)
    bus.register(failing_mock)

    from backend.models.agent_tasks import VisionTask, IntentTask
    results = await bus.dispatch_parallel(
        [
            (AgentType.VISION, VisionTask()),
            (AgentType.INTENT, IntentTask(product_description="mug")),
        ],
        saga_id="s1",
    )

    assert len(results) == 2
    vision_result = next(r for r in results if r.agent_type == AgentType.VISION)
    intent_result = next(r for r in results if r.agent_type == AgentType.INTENT)

    assert vision_result.status == "success"
    assert intent_result.status == "failure"
