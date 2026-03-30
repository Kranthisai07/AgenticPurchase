"""
SourcingAgent — searches a single vendor source for product listings.

One class, instantiated once in the AgentBus.
Implements ReAct reasoning loop:
  1. Formulate query
  2. Search
  3. Evaluate results → retry with relaxed query if zero results
  4. Filter by price range
  5. Return with metadata

Sources: ebay, serpapi
Etsy removed — API key not available
"""
from typing import Any, Literal

from backend.agents.base import BaseAgent
from backend.agents.sourcing.query_builder import (
    build_ebay_query,
    build_serpapi_query,
    relax_query,
)
from backend.integrations.ebay.client import EbayClient
from backend.integrations.ebay.normalizer import normalize_ebay_items
from backend.integrations.serpapi.client import SerpApiClient
from backend.integrations.serpapi.normalizer import normalize_serpapi_results
from backend.models.agent_messages import AgentType
from backend.models.agent_results import SourcingFailure, SourcingSuccess
from backend.models.agent_tasks import SourcingTask
from backend.models.offer import Offer


def filter_by_price(
    offers: list[Offer], price_min: float | None, price_max: float | None
) -> list[Offer]:
    result = offers
    if price_min is not None:
        result = [o for o in result if o.price.amount >= price_min]
    if price_max is not None:
        result = [o for o in result if o.price.amount <= price_max]
    return result


def deduplicate_offers(offers: list[Offer]) -> list[Offer]:
    """Remove exact-URL duplicates."""
    seen: set[str] = set()
    unique = []
    for offer in offers:
        if offer.url not in seen:
            seen.add(offer.url)
            unique.append(offer)
    return unique


class SourcingAgent(BaseAgent):
    """
    Single class registered once in the AgentBus.
    Source ("ebay" | "serpapi") is determined by task.source at runtime,
    so one instance handles both sources without coupling.
    """

    agent_type = AgentType.SOURCING
    timeout = 20

    def __init__(
        self,
        ebay_client: EbayClient | None = None,
        serpapi_client: SerpApiClient | None = None,
    ) -> None:
        super().__init__()
        self._ebay = ebay_client or EbayClient()
        self._serpapi = serpapi_client or SerpApiClient()

    async def _execute(self, task: SourcingTask) -> SourcingSuccess | SourcingFailure:
        intent = task.parsed_intent
        attempt = task.attempt
        # Use task.source so the same agent instance can handle any vendor
        self.source = task.source  # type: ignore[assignment]

        try:
            offers, query_used = await self._search(intent, relaxed=(attempt > 1))
        except Exception as exc:
            error_str = str(exc).lower()
            if "401" in error_str or "403" in error_str or "auth" in error_str:
                return SourcingFailure(
                    source=self.source,
                    error="auth_failed",
                    suggested_query_relaxation=None,
                )
            if "timeout" in error_str:
                return SourcingFailure(
                    source=self.source,
                    error="timeout",
                    suggested_query_relaxation=relax_query(intent.primary_query, intent),
                )
            return SourcingFailure(
                source=self.source,
                error="api_unavailable",
                suggested_query_relaxation=None,
            )

        if not offers:
            if attempt < 2:
                # Retry once with relaxed query
                relaxed_q = relax_query(query_used, intent)
                self._logger.info(
                    "sourcing.zero_results.retrying",
                    source=self.source,
                    original=query_used,
                    relaxed=relaxed_q,
                )
                try:
                    offers, query_used = await self._search(intent, relaxed=True)
                except Exception:
                    pass

            if not offers:
                return SourcingFailure(
                    source=self.source,
                    error="zero_results",
                    suggested_query_relaxation=relax_query(intent.primary_query, intent),
                )

        # Filter by price range
        filtered = filter_by_price(offers, intent.price_min, intent.price_max)
        if not filtered and offers:
            filtered = offers  # don't apply price filter if it removes everything

        deduped = deduplicate_offers(filtered)
        top = deduped[:10]

        return SourcingSuccess(
            source=self.source,
            offers=top,
            query_used=query_used,
            result_count=len(top),
            is_sparse=len(top) < 3,
        )

    async def _search(
        self, intent: Any, relaxed: bool = False
    ) -> tuple[list[Offer], str]:
        if self.source == "ebay":
            query, filters = build_ebay_query(intent)
            if relaxed:
                query = relax_query(query, intent)
            raw = await self._ebay.ebay_search(query, filters)
            return normalize_ebay_items(raw), query

        else:  # serpapi
            query = build_serpapi_query(intent)
            if relaxed:
                query = relax_query(query, intent)
            raw = await self._serpapi.google_shopping_search(query)
            return normalize_serpapi_results(raw), query

    async def _self_evaluate(self, result: Any) -> tuple[bool, str]:
        # Failures are valid agent outcomes — pass through
        if isinstance(result, SourcingFailure):
            return True, ""
        if isinstance(result, SourcingSuccess):
            if result.result_count == 0:
                return False, "result_count is 0 despite success status"
        return True, ""
