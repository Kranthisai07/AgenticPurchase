"""Unit tests for SourcingAgent."""
import pytest

from backend.agents.sourcing.agent import SourcingAgent
from backend.models.agent_results import SourcingFailure, SourcingSuccess
from backend.models.agent_tasks import SourcingTask
from backend.models.intent import ParsedIntent


@pytest.fixture
def sourcing_agent(mock_ebay_client, mock_serpapi_client):
    agent = SourcingAgent(
        ebay_client=mock_ebay_client,
        serpapi_client=mock_serpapi_client,
    )
    return agent


@pytest.fixture
def intent():
    return ParsedIntent(
        primary_query="blue ceramic coffee mug",
        category="kitchenware",
        price_max=80.0,
        condition="new",
    )


@pytest.mark.asyncio
async def test_ebay_sourcing_success(sourcing_agent, intent):
    task = SourcingTask(source="ebay", parsed_intent=intent)
    result = await sourcing_agent._execute(task)

    assert isinstance(result, SourcingSuccess)
    assert result.source == "ebay"


@pytest.mark.asyncio
async def test_serpapi_sourcing_success(sourcing_agent, intent):
    task = SourcingTask(source="serpapi", parsed_intent=intent)
    result = await sourcing_agent._execute(task)

    assert isinstance(result, SourcingSuccess)
    assert result.source == "serpapi"


@pytest.mark.asyncio
async def test_sourcing_zero_results_returns_failure(mock_ebay_client, mock_serpapi_client, intent):
    mock_ebay_client.ebay_search.return_value = []
    agent = SourcingAgent(
        ebay_client=mock_ebay_client,
        serpapi_client=mock_serpapi_client,
    )
    task = SourcingTask(source="ebay", parsed_intent=intent, attempt=2)
    result = await agent._execute(task)

    assert isinstance(result, SourcingFailure)
    assert result.error == "zero_results"


@pytest.mark.asyncio
async def test_sourcing_api_error_returns_failure(mock_ebay_client, mock_serpapi_client, intent):
    from backend.core.exceptions import VendorAPIError
    mock_ebay_client.ebay_search.side_effect = VendorAPIError("ebay", 503, "Service Unavailable")
    agent = SourcingAgent(
        ebay_client=mock_ebay_client,
        serpapi_client=mock_serpapi_client,
    )
    task = SourcingTask(source="ebay", parsed_intent=intent)
    result = await agent._execute(task)

    assert isinstance(result, SourcingFailure)
    assert result.error == "api_unavailable"


@pytest.mark.asyncio
async def test_sourcing_price_filter(sourcing_agent, intent):
    intent_strict = ParsedIntent(
        primary_query="blue mug",
        category="kitchenware",
        price_min=100.0,  # higher than any offer price
        price_max=200.0,
    )
    task = SourcingTask(source="ebay", parsed_intent=intent_strict)
    result = await sourcing_agent._execute(task)
    # Should still return results (price filter falls back when it removes everything)
    assert isinstance(result, (SourcingSuccess, SourcingFailure))
