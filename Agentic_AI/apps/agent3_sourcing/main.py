# -*- coding: utf-8 -*-
import json
import logging
import os
import uuid
from functools import lru_cache
from typing import Dict, List

from ...libs.agents.sourcing_chain import rerank_offers_with_llm
from ..coordinator.metrics_tokens import TokenBudgeter
from ..coordinator.config import TOKEN_BUDGETS, TOKEN_POLICY
from ...libs.schemas.models import Offer, PurchaseIntent

CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "mock_catalog.json",
)

MOCK_SITE_BASE = os.getenv("MOCK_SITE_BASE", "http://127.0.0.1:8000/mock")

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_catalog() -> List[Dict]:
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _norm(values: List[float]) -> List[float]:
    if not values:
        return []
    mn, mx = min(values), max(values)
    if abs(mx - mn) < 1e-9:
        return [0.5 for _ in values]
    return [(v - mn) / (mx - mn) for v in values]


def _filter_items_fuzzy(pi: PurchaseIntent, catalog: list) -> list:
    filtered = catalog
    if pi.category:
        by_cat = [c for c in catalog if c.get("category") == pi.category]
        if by_cat:
            filtered = by_cat
    query = (pi.item_name or "").lower().strip()
    if query:
        matches = [
            c for c in filtered
            if query in c["title"].lower()
            or any(query in (kw or "").lower() for kw in c.get("keywords", []))
        ]
        if not matches:
            tokens = [tok for tok in query.split() if len(tok) > 2]
            matches = [
                c
                for c in filtered
                if any(
                    tok in c["title"].lower()
                    or any(tok in (kw or "").lower() for kw in c.get("keywords", []))
                    for tok in tokens
                )
            ]
        if matches:
            filtered = matches
    return filtered


def _filter_items_strict(pi: PurchaseIntent, catalog: list) -> list:
    """Strict filter: require category match when present and enforce brand/family tokens.

    - If `pi.category` is set, only keep that category.
    - If `pi.brand` exists, require it in title/keywords.
    - If `pi.item_name` has tokens (>= 1), require at least one token match in title/keywords.
    """
    items = catalog
    if pi.category:
        items = [c for c in items if c.get("category") == pi.category]
    title_key = "title"
    kw_key = "keywords"

    def _has(term: str, it: dict) -> bool:
        t = (it.get(title_key) or "").lower()
        kws = [str(k or "").lower() for k in it.get(kw_key, [])]
        term = (term or "").lower()
        return (term and term in t) or any(term in k for k in kws)

    # Enforce brand token when available
    if pi.brand:
        brand = (pi.brand or "").lower()
        items = [it for it in items if _has(brand, it)]

    # Enforce at least one token from item_name
    tokens = [tok for tok in (pi.item_name or "").lower().split() if len(tok) > 2]
    if tokens:
        _tmp = []
        for it in items:
            if any(_has(tok, it) for tok in tokens):
                _tmp.append(it)
        items = _tmp
    return items


def _match_bonus(pi: PurchaseIntent, item: dict) -> float:
    bonus = 0.0
    title = item.get("title", "").lower()
    keywords = [kw.lower() for kw in item.get("keywords", [])]
    if pi.brand:
        brand = pi.brand.lower()
        if brand and (brand in title or any(brand in kw for kw in keywords)):
            bonus += 0.25
    if pi.color:
        color = pi.color.lower()
        if color and (color in title or any(color in kw for kw in keywords)):
            bonus += 0.15
    if pi.item_name:
        name = pi.item_name.lower()
        if name in title or any(name in kw for kw in keywords):
            bonus += 0.2
    if pi.budget_usd and item.get("price_usd") and item["price_usd"] <= pi.budget_usd:
        bonus += 0.1
    return bonus


def _rewrite_url(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    return f"{MOCK_SITE_BASE}/{slug}"


def _score_item(pi: PurchaseIntent, item: dict, idx: int, price_norm: list, ship_norm: list, eta_norm: list) -> Offer:
    base = (1 - price_norm[idx]) * 0.6 + (1 - ship_norm[idx]) * 0.2 + (1 - eta_norm[idx]) * 0.2
    bonus = _match_bonus(pi, item)
    payload = dict(item)
    payload["score"] = float(round(base + bonus, 4))
    if payload.get("url"):
        payload["url"] = _rewrite_url(payload["url"])
    payload.setdefault("tags", list(payload.get("keywords", [])))
    payload.setdefault("image_url", "")
    payload.setdefault("description", "")
    return Offer(**payload)


def _best_budget_fallback(pi: PurchaseIntent, catalog: list, top_k: int) -> List[Offer]:
    budget_items = [c for c in catalog if pi.budget_usd and c.get("price_usd") <= pi.budget_usd]
    budget_items.sort(key=lambda c: c.get("price_usd", 0))
    offers = []
    for item in budget_items[:top_k]:
        payload = dict(item)
        payload["score"] = 0.5
        if payload.get("url"):
            payload["url"] = _rewrite_url(payload["url"])
        offers.append(Offer(**payload))
    return offers


async def _score_candidates(pi: PurchaseIntent, candidates: list, catalog: list, top_k: int = 5,
                            *, token_budgets: Dict[str, Dict[str, int]] | None = None,
                            token_policy: str | None = None) -> List[Offer]:

    prices = [c["price_usd"] for c in candidates]
    ships = [c["shipping_days"] for c in candidates]
    etas = [c.get("eta_days", 0) for c in candidates]
    price_norm = _norm(prices)
    ship_norm = _norm(ships)
    eta_norm = _norm(etas)

    offers = [
        _score_item(pi, item, idx, price_norm, ship_norm, eta_norm)
        for idx, item in enumerate(candidates)
    ]

    offers.sort(key=lambda offer: offer.score, reverse=True)
    shortlisted = offers[:top_k]

    if not shortlisted and pi.budget_usd:
        shortlisted = _best_budget_fallback(pi, catalog, top_k)

    if _langchain_enabled() and shortlisted:
        try:
            run_id = str(uuid.uuid4())[:8]
            budgets = token_budgets or TOKEN_BUDGETS
            policy = token_policy or TOKEN_POLICY
            budgeter = TokenBudgeter(run_id, budgets, policy)
            shortlisted = await rerank_offers_with_llm(pi, shortlisted, budgeter=budgeter, state="S3")
        except Exception as exc:
            logger.warning("LangChain sourcing rerank failed: %s", exc, exc_info=True)

    return shortlisted


async def offers_for_intent(
    pi: PurchaseIntent,
    top_k: int = 5,
    *,
    token_budgets: Dict[str, Dict[str, int]] | None = None,
    token_policy: str | None = None,
) -> List[Offer]:
    """Default (fuzzy) strategy for backward compatibility."""
    catalog = _load_catalog()
    candidates = _filter_items_fuzzy(pi, catalog) or catalog
    return await _score_candidates(pi, candidates, catalog, top_k, token_budgets=token_budgets, token_policy=token_policy)


async def offers_for_intent_strict(
    pi: PurchaseIntent,
    top_k: int = 5,
    *,
    token_budgets: Dict[str, Dict[str, int]] | None = None,
    token_policy: str | None = None,
) -> List[Offer]:
    catalog = _load_catalog()
    candidates = _filter_items_strict(pi, catalog)
    return await _score_candidates(pi, candidates or [], catalog, top_k, token_budgets=token_budgets, token_policy=token_policy)


async def offers_for_intent_fuzzy(
    pi: PurchaseIntent,
    top_k: int = 5,
    *,
    token_budgets: Dict[str, Dict[str, int]] | None = None,
    token_policy: str | None = None,
) -> List[Offer]:
    catalog = _load_catalog()
    candidates = _filter_items_fuzzy(pi, catalog) or catalog
    return await _score_candidates(pi, candidates, catalog, top_k, token_budgets=token_budgets, token_policy=token_policy)


def _langchain_enabled() -> bool:
    flag = os.getenv("USE_LANGCHAIN_SOURCING", os.getenv("USE_LANGCHAIN", "0"))
    return flag is not None and flag.strip().lower() in {"1", "true", "yes"}


