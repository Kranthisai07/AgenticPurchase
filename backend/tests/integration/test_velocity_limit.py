"""Tests that velocity limiting blocks excessive checkout attempts."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agents.checkout.agent import CheckoutAgent
from backend.core.velocity import SlidingWindowRateLimiter
from backend.models.agent_results import CheckoutFailure, CheckoutSuccess
from backend.models.agent_tasks import CheckoutTask


@pytest.fixture
def mock_redis(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    # eval() is used by SlidingWindowRateLimiter Lua script
    # Return [1, 2] = allowed=True, remaining=2
    redis.eval = AsyncMock(return_value=[1, 2])
    redis.pipeline = MagicMock(return_value=AsyncMock(
        incr=AsyncMock(),
        expire=AsyncMock(),
        execute=AsyncMock(return_value=[1, True]),
    ))
    monkeypatch.setattr("backend.core.redis.get_redis", lambda: redis)
    monkeypatch.setattr("backend.agents.checkout.idempotency.get_redis", lambda: redis)
    return redis


@pytest.mark.asyncio
async def test_velocity_limit_blocks_at_threshold(
    sample_ranked_offer, sample_address, mock_stripe_client, mock_redis
):
    mock_redis.get.return_value = None  # no idempotency cache

    agent = CheckoutAgent.__new__(CheckoutAgent)
    agent._stripe = mock_stripe_client
    agent._redis = mock_redis
    agent.llm = None
    agent.tools = []
    import structlog
    agent._logger = structlog.get_logger("test")
    from backend.core.config import get_settings
    agent._settings = get_settings()

    task = CheckoutTask(
        saga_id="saga-vel",
        selected_offer=sample_ranked_offer,
        stripe_payment_method_id="pm_test",
        shipping_address=sample_address,
        user_id="user-velocity",
    )

    with patch.object(
        SlidingWindowRateLimiter,
        "check_and_increment",
        AsyncMock(return_value=(False, 0)),  # blocked
    ):
        result = await agent._execute(task)

    assert isinstance(result, CheckoutFailure)
    assert result.error == "velocity_limit_exceeded"
    assert result.retry_allowed is False
    mock_stripe_client.stripe_create_payment_intent.assert_not_called()


@pytest.mark.asyncio
async def test_velocity_limit_allows_under_threshold(
    sample_ranked_offer, sample_address, mock_stripe_client, mock_redis
):
    mock_redis.get.return_value = None

    agent = CheckoutAgent.__new__(CheckoutAgent)
    agent._stripe = mock_stripe_client
    agent._redis = mock_redis
    agent.llm = None
    agent.tools = []
    import structlog
    agent._logger = structlog.get_logger("test")
    from backend.core.config import get_settings
    agent._settings = get_settings()

    task = CheckoutTask(
        saga_id="saga-vel2",
        selected_offer=sample_ranked_offer,
        stripe_payment_method_id="pm_test",
        shipping_address=sample_address,
        user_id="user-velocity2",
    )

    with patch.object(
        SlidingWindowRateLimiter,
        "check_and_increment",
        AsyncMock(return_value=(True, 1)),  # allowed with 1 remaining
    ):
        result = await agent._execute(task)

    assert isinstance(result, CheckoutSuccess)
