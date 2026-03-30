"""
Sourcing evaluation — NDCG@3 and MRR against relevance labels derived from
brand/product-type keyword matching.

Relevance labeling (binary):
  RELEVANT if:
    - offer.title (lowercased) contains any brand keyword (len >= 4) from
      query.authentic_brand_keywords, OR
    - offer.title contains any word from query.expected_product_type
  NOT RELEVANT if:
    - offer.title contains any suspicious keyword from
      query.suspicious_title_keywords (regardless of brand match)

NDCG@3: computed over the top-3 ranked_offers (in ranking order).
MRR:    first relevant rank among ranked_offers.

Both metrics are averaged across all successfully completed sagas.
All math uses stdlib only — no numpy, no sklearn.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backend.evaluation.dataset import EvalQuery


@dataclass
class SourcingMetrics:
    ndcg_at_3: float
    mrr: float
    n_queries: int
    avg_offers_returned: float


def evaluate_sourcing(saga_results: list) -> SourcingMetrics:
    """
    Compute NDCG@3 and MRR for the sourcing + ranking pipeline.

    Parameters
    ----------
    saga_results : list[SagaEvalResult]
        Each result must have:
          .query          EvalQuery
          .ranked_offers  list of RankedOffer (or any object with .title attribute)
          .sourced_offers list of Offer
          .success        bool

    Returns
    -------
    SourcingMetrics
    """
    ndcg_scores: list[float] = []
    rr_scores:   list[float] = []
    offer_counts: list[int]  = []

    for sr in saga_results:
        if not sr.success:
            continue

        query: EvalQuery = sr.query
        ranked = sr.ranked_offers or []

        offer_counts.append(len(sr.sourced_offers or []))

        # Full pool of offers for price context
        all_offers = sr.sourced_offers or ranked

        # Count total relevant offers in the full pool
        total_relevant = sum(
            1 for o in all_offers if _is_relevant(o, query, all_offers)
        )

        # NDCG@3 over top-3 ranked
        top3 = ranked[:3]
        rel_labels = [1 if _is_relevant(o, query, all_offers) else 0 for o in top3]

        dcg  = _dcg(rel_labels)
        idcg = _idcg(min(3, total_relevant))
        ndcg = dcg / idcg if idcg > 0 else 0.0
        ndcg_scores.append(ndcg)

        # MRR: first rank of a relevant offer in the full ranked list
        rr = 0.0
        for rank_idx, offer in enumerate(ranked, start=1):
            if _is_relevant(offer, query, all_offers):
                rr = 1.0 / rank_idx
                break
        rr_scores.append(rr)

    n = len(ndcg_scores)
    if n == 0:
        return SourcingMetrics(ndcg_at_3=0.0, mrr=0.0, n_queries=0, avg_offers_returned=0.0)

    return SourcingMetrics(
        ndcg_at_3=round(sum(ndcg_scores) / n, 4),
        mrr=round(sum(rr_scores) / n, 4),
        n_queries=n,
        avg_offers_returned=round(sum(offer_counts) / n, 2),
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _is_relevant(offer: object, query: EvalQuery, batch_offers: list) -> bool:
    """
    Stricter binary relevance label for a single offer.

    Previous (circular) logic: relevant if title contains the brand keyword
    that was searched for — but search APIs return brand-matching results by
    construction, so this inflated NDCG/MRR to ~0.97/0.98 regardless of
    ranking quality.

    New independent criterion:
      1. Title must NOT contain suspicious keywords.
      2. Price must be within 3× the batch median (filters anomalous pricing).
      3. Title must contain BOTH a product-type word (word-boundary) AND the
         brand as a whole word from the title word set.
         Brand matching uses word tokenisation, not substring, to avoid
         "nike" matching "nikeshoes123" etc.

    Relevant only when ALL three conditions pass.
    """
    title = (getattr(offer, "title", "") or "").lower()

    # Rule 1: suspicious keywords override everything
    for kw in query.suspicious_title_keywords:
        if kw.lower() in title:
            return False

    # Rule 2: price must be within 3× batch median
    try:
        offer_currency = getattr(getattr(offer, "price", None), "currency", None)
        offer_price    = getattr(getattr(offer, "price", None), "amount", None)
        if offer_price is not None and offer_currency is not None:
            prices = [
                float(getattr(getattr(o, "price", None), "amount", 0))
                for o in batch_offers
                if (
                    getattr(getattr(o, "price", None), "amount", None) is not None
                    and getattr(getattr(o, "price", None), "currency", None) == offer_currency
                )
            ]
            if len(prices) >= 3:
                sorted_p = sorted(prices)
                median = sorted_p[len(sorted_p) // 2]
                if median > 0 and float(offer_price) > median * 3:
                    return False  # implausibly expensive relative to batch
    except (TypeError, ValueError, AttributeError):
        pass  # if price data is malformed, don't penalise the offer

    # Rule 3: title must contain BOTH product-type word AND brand whole-word
    type_words  = [w for w in (query.expected_product_type or "").lower().split() if len(w) >= 4]
    brand_words = [w.lower() for w in (query.expected_brand or "").split() if len(w) >= 4]

    # Word-tokenised title for whole-word brand check
    title_words = set(title.replace("-", " ").replace("'", " ").split())

    has_type_match  = any(w in title for w in type_words)
    has_brand_match = any(bw in title_words for bw in brand_words)

    return has_type_match and has_brand_match


def _dcg(rel_labels: list[int]) -> float:
    """DCG for a ranked list of binary relevance labels."""
    return sum(
        rel / math.log2(i + 2)  # log2(rank+1), rank is 0-based → log2(i+2)
        for i, rel in enumerate(rel_labels)
    )


def _idcg(n_relevant: int) -> float:
    """Ideal DCG assuming n_relevant items at the top positions."""
    if n_relevant <= 0:
        return 0.0
    return sum(1.0 / math.log2(i + 2) for i in range(n_relevant))
