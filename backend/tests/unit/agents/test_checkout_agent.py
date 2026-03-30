"""Unit tests for CheckoutAgent."""
import pytest
from unittest.mock import AsyncMock, patch

from backend.agents.checkout.agent import CheckoutAgent
from backend.core.velocity import SlidingWindowRateLimiter
from backend.models.agent_results import CheckoutFailure, CheckoutSuccess
from backend.models.agent_tasks import CheckoutTask


@pytest.fixture
def mock_redis(monkeypatch):
    from unittest.mock import MagicMock
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


@pytest.fixture
def checkout_agent(mock_stripe_client, mock_redis):
    agent = CheckoutAgent.__new__(CheckoutAgent)
    agent._stripe = mock_stripe_client
    agent._redis = mock_redis
    agent.llm = None
    agent.tools = []
    import structlog
    agent._logger = structlog.get_logger("test")
    from backend.core.config import get_settings
    agent._settings = get_settings()
    return agent


@pytest.fixture
def checkout_task(sample_ranked_offer, sample_address):
    return CheckoutTask(
        saga_id="saga-123",
        selected_offer=sample_ranked_offer,
        stripe_payment_method_id="pm_test_abc",
        shipping_address=sample_address,
        user_id="user-456",
    )


@pytest.mark.asyncio
async def test_checkout_success(checkout_agent, checkout_task, mock_redis):
    mock_redis.get.return_value = None  # no idempotency cache hit
    result = await checkout_agent._execute(checkout_task)

    assert isinstance(result, CheckoutSuccess)
    assert result.client_secret == "pi_test_123_secret_abc"
    assert result.receipt_id is not None


@pytest.mark.asyncio
async def test_checkout_idempotency(checkout_agent, checkout_task, mock_redis):
    import json
    cached_result = {"client_secret": "cached_secret", "receipt_id": "cached-receipt", "estimated_delivery": None}
    mock_redis.get.return_value = json.dumps(cached_result)

    result = await checkout_agent._execute(checkout_task)

    assert isinstance(result, CheckoutSuccess)
    assert result.client_secret == "cached_secret"
    # Stripe should NOT have been called
    checkout_agent._stripe.stripe_create_payment_intent.assert_not_called()


@pytest.mark.asyncio
async def test_checkout_velocity_exceeded(checkout_agent, checkout_task, mock_redis):
    with patch.object(
        SlidingWindowRateLimiter,
        "check_and_increment",
        AsyncMock(return_value=(False, 0)),  # blocked
    ):
        result = await checkout_agent._execute(checkout_task)

    assert isinstance(result, CheckoutFailure)
    assert result.error == "velocity_limit_exceeded"
    assert result.retry_allowed is False


@pytest.mark.asyncio
async def test_checkout_stripe_card_error(checkout_agent, checkout_task, mock_redis):
    import stripe
    mock_redis.get.return_value = None

    checkout_agent._stripe.stripe_create_payment_intent.side_effect = stripe.error.CardError(
        "Card declined", None, "card_declined"
    )

    result = await checkout_agent._execute(checkout_task)

    assert isinstance(result, CheckoutFailure)
    assert result.error == "payment_declined"
    assert result.retry_allowed is True


@pytest.mark.asyncio
async def test_checkout_self_eval_rejects_empty_secret(checkout_agent):
    result = CheckoutSuccess(client_secret="", receipt_id="r1")
    ok, reason = await checkout_agent._self_evaluate(result)
    assert ok is False
    assert "client_secret" in reason
