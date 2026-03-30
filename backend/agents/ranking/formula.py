"""
Composite ranking formula.

Score breakdown (max 100 points):
  price_score:       (1 - normalised_price) * 25    → lower price = higher score
  trust_score:       (trust / 100) * 35             → trust is most weighted
  relevance_score:   similarity * 20                → semantic match to intent
  rating_score:      (seller_rating / 5) * 15       → seller quality
  shipping_score:    (free ? 1.0 : 0.5) * 5        → free shipping bonus

Tie-breaking (within 2 composite points):
  1. Higher review_count wins
  2. Still tied → lower price wins
"""
from backend.models.offer import RankedOffer, ScoredOffer


def normalize_prices(offers: list[ScoredOffer]) -> tuple[float, float]:
    """Return (min_price, max_price) across all offers."""
    prices = [o.price.amount for o in offers if o.price.amount > 0]
    if not prices:
        return 0.0, 1.0
    return min(prices), max(prices)


def compute_price_score(price: float, min_p: float, max_p: float) -> float:
    if max_p == min_p:
        return 12.5  # all same price → mid score
    normalised = (price - min_p) / (max_p - min_p)
    return (1 - normalised) * 25.0


def compute_trust_component(trust_score: float) -> float:
    return (trust_score / 100.0) * 35.0


def compute_relevance_score(offer_title: str, query: str) -> float:
    """
    Simple token overlap relevance score (0-1).
    In production this would use embedding cosine similarity.
    """
    query_tokens = set(query.lower().split())
    title_tokens = set(offer_title.lower().split())
    if not query_tokens:
        return 0.5
    overlap = len(query_tokens & title_tokens) / len(query_tokens)
    return min(overlap, 1.0)


def compute_rating_score(rating: float | None) -> float:
    if rating is None:
        return 7.5  # neutral mid score when unknown
    return (min(max(rating, 0.0), 5.0) / 5.0) * 15.0


def compute_shipping_score(free_shipping: bool) -> float:
    return 5.0 if free_shipping else 2.5


def rank_offers(
    scored_offers: list[ScoredOffer],
    query: str,
) -> list[RankedOffer]:
    """Rank all offers by composite score. Returns sorted list (best first)."""
    if not scored_offers:
        return []

    min_p, max_p = normalize_prices(scored_offers)

    composites: list[tuple[float, ScoredOffer, float, float, float, float]] = []
    for offer in scored_offers:
        price_s = compute_price_score(offer.price.amount, min_p, max_p)
        trust_c = compute_trust_component(offer.trust_score.score)
        rel_s = compute_relevance_score(offer.title, query) * 20.0
        rating_s = compute_rating_score(offer.trust_score.signals.rating)
        ship_s = compute_shipping_score(offer.free_shipping)
        composite = price_s + trust_c + rel_s + rating_s + ship_s
        composites.append((composite, offer, price_s, rel_s, rating_s, ship_s))

    # Sort by composite desc, then review_count desc, then price asc
    composites.sort(
        key=lambda x: (
            -x[0],
            -(x[1].trust_score.signals.review_count or 0),
            x[1].price.amount,
        )
    )

    ranked: list[RankedOffer] = []
    for rank, (composite, offer, price_s, rel_s, rating_s, ship_s) in enumerate(
        composites[:5], start=1
    ):
        ranked.append(
            RankedOffer(
                **offer.model_dump(),
                composite_score=round(composite, 2),
                rank=rank,
                price_score=round(price_s, 2),
                relevance_score=round(rel_s, 2),
                rating_score=round(rating_s, 2),
                shipping_score=round(ship_s, 2),
            )
        )
    return ranked


def detect_near_tie(ranked: list[RankedOffer], threshold: float = 2.0) -> bool:
    """Return True if the top 2 offers are within `threshold` composite points."""
    if len(ranked) < 2:
        return False
    return abs(ranked[0].composite_score - ranked[1].composite_score) <= threshold
