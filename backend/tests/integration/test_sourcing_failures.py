"""Tests all sourcing failure modes."""
import pytest
from unittest.mock import AsyncMock

from backend.agents.sourcing.agent import SourcingAgent
from backend.models.agent_results import SourcingFailure, SourcingSuccess
from backend.models.agent_tasks import SourcingTask
from backend.models.intent import ParsedIntent


@pytest.fixture
def intent():
    return ParsedIntent(primary_query="test product", category="general")


@pytest.mark.asyncio
async def test_all_sources_fail_returns_two_failures(intent):
    from backend.core.exceptions import VendorAPIError

    ebay = AsyncMock()
    serpapi = AsyncMock()
    ebay.ebay_search.side_effect = VendorAPIError("ebay", 503, "down")
    serpapi.google_shopping_search.side_effect = VendorAPIError("serpapi", 503, "down")

    agent = SourcingAgent(ebay_client=ebay, serpapi_client=serpapi)

    for source in ["ebay", "serpapi"]:
        result = await agent._execute(SourcingTask(source=source, parsed_intent=intent, attempt=2))
        assert isinstance(result, SourcingFailure)
        assert result.source == source


@pytest.mark.asyncio
async def test_auth_failure_reported_correctly(intent):
    from backend.core.exceptions import VendorAPIError

    ebay = AsyncMock()
    ebay.ebay_search.side_effect = VendorAPIError("ebay", 401, "Unauthorized")
    agent = SourcingAgent(ebay_client=ebay, serpapi_client=AsyncMock())

    result = await agent._execute(SourcingTask(source="ebay", parsed_intent=intent))
    assert isinstance(result, SourcingFailure)
    assert result.error == "auth_failed"


@pytest.mark.asyncio
async def test_zero_results_after_retry_returns_failure(intent):
    ebay = AsyncMock()
    ebay.ebay_search.return_value = []  # always empty

    agent = SourcingAgent(ebay_client=ebay, serpapi_client=AsyncMock())
    result = await agent._execute(SourcingTask(source="ebay", parsed_intent=intent, attempt=2))

    assert isinstance(result, SourcingFailure)
    assert result.error == "zero_results"
    assert result.suggested_query_relaxation is not None


@pytest.mark.asyncio
async def test_partial_failure_does_not_block_other_sources(intent):
    from backend.core.exceptions import VendorAPIError

    ebay = AsyncMock()
    serpapi = AsyncMock()

    ebay.ebay_search.side_effect = VendorAPIError("ebay", 503, "down")
    serpapi.google_shopping_search.return_value = [
        {
            "title": "Product",
            "extracted_price": 25.00,
            "source": "Amazon",
            "link": "https://amazon.com/1",
            "thumbnail": "",
        }
    ]

    agent_ebay = SourcingAgent(ebay_client=ebay, serpapi_client=serpapi)
    agent_serpapi = SourcingAgent(ebay_client=ebay, serpapi_client=serpapi)

    ebay_result = await agent_ebay._execute(SourcingTask(source="ebay", parsed_intent=intent))
    serpapi_result = await agent_serpapi._execute(SourcingTask(source="serpapi", parsed_intent=intent))

    assert isinstance(ebay_result, SourcingFailure)
    assert isinstance(serpapi_result, SourcingSuccess)
    assert serpapi_result.result_count > 0
