"""
Per-source query syntax translation.
Each vendor has its own search syntax and supported filter parameters.

Sources: ebay, serpapi
Etsy removed — API key not available
"""
from typing import Any

from backend.models.intent import ParsedIntent


def build_ebay_query(intent: ParsedIntent) -> tuple[str, dict[str, Any]]:
    """Build an eBay Browse API query and filter dict."""
    query = intent.primary_query
    filters: dict[str, Any] = {}

    if intent.price_min is not None:
        filters["min_price"] = intent.price_min
    if intent.price_max is not None:
        filters["max_price"] = intent.price_max
    if intent.condition and intent.condition != "any":
        filters["condition"] = intent.condition
    if intent.urgency == "fast_shipping":
        filters["fast_shipping"] = True

    return query, filters


def build_serpapi_query(intent: ParsedIntent) -> str:
    """Build a Google Shopping query string."""
    parts = [intent.primary_query]

    if intent.price_max:
        parts.append(f"under ${int(intent.price_max)}")
    if intent.condition == "new":
        parts.append("new")

    return " ".join(parts)


def relax_query(query: str, intent: ParsedIntent) -> str:
    """
    Return a relaxed version of the query by removing the most specific constraint.
    Used when the first search attempt returns zero results.
    """
    # Strategy: remove the last word (usually the most specific attribute)
    words = query.strip().split()
    if len(words) > 2:
        return " ".join(words[:-1])
    # Fall back to category only
    return intent.category
