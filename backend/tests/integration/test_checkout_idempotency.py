"""Tests that double checkout submissions do not result in double charges."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agents.checkout.agent import CheckoutAgent
from backend.agents.checkout.idempotency import generate_checkout_idempotency_key
from backend.core.velocity import SlidingWindowRateLimiter
from backend.models.agent_results import CheckoutSuccess
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


def test_same_inputs_produce_same_key():
    key1 = generate_checkout_idempotency_key("saga-1", "offer-1", "user-1")
    key2 = generate_checkout_idempotency_key("saga-1", "offer-1", "user-1")
    assert key1 == key2


def test_different_saga_produces_different_key():
    key1 = generate_checkout_idempotency_key("saga-1", "offer-1", "user-1")
    key2 = generate_checkout_idempotency_key("saga-2", "offer-1", "user-1")
    assert key1 != key2


@pytest.mark.asyncio
async def test_duplicate_checkout_returns_cached_result(
    sample_ranked_offer, sample_address, mock_stripe_client, mock_redis
):
    cached_success = CheckoutSuccess(
        client_secret="cached_pi_secret",
        receipt_id="cached-receipt-id",
    )
    mock_redis.get.return_value = json.dumps(cached_success.model_dump())

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
        saga_id="saga-dup",
        selected_offer=sample_ranked_offer,
        stripe_payment_method_id="pm_test",
        shipping_address=sample_address,
        user_id="user-1",
    )

    with patch.object(
        SlidingWindowRateLimiter,
        "check_and_increment",
        AsyncMock(return_value=(True, 2)),  # allowed
    ):
        result = await agent._execute(task)

    assert isinstance(result, CheckoutSuccess)
    assert result.client_secret == "cached_pi_secret"
    mock_stripe_client.stripe_create_payment_intent.assert_not_called()
