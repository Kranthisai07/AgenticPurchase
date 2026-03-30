"""
Trust Framework — Session 1: Deterministic heuristic signals.

Computes 4 signals for every offer in the batch without any LLM calls:
  1. Price Z-score           — statistical outlier detection across the batch
  2. Replica keyword sweep   — title + description regex scan
  3. Brand-metadata check    — Vision-detected brand vs listing brand
  4. Weight anomaly          — physical weight vs category norms

All logic is pure Python: no I/O, no external calls, fully deterministic.
Designed to be called from TrustAgent before the LLM Session 2 pass.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# ── Replica keyword patterns ──────────────────────────────────────────────────

_REPLICA_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\breplica\b",
        r"\bcounterfeit\b",
        r"\bfake\b",
        r"\bknock[-\s]?off\b",
        r"\bimitation\b",
        r"\bnot\s+authentic\b",
        r"\bnot\s+genuine\b",
        r"\bnot\s+original\b",
        r"\binspired\s+by\b",
        r"\bAAA\+",
        r"1:1\s+copy",
        r"1:1\s+clone",
        r"\bhigh\s+quality\s+copy\b",
        r"\bdupe\b",
        r"\bbootleg\b",
    ]
]

# ── Category weight norms (min_grams, max_grams) ──────────────────────────────

_WEIGHT_NORMS: dict[str, tuple[float, float]] = {
    "sneaker":      (150.0, 800.0),
    "running shoe": (150.0, 800.0),
    "shoe":         (150.0, 800.0),
    "watch":        (30.0,  350.0),
    "smartphone":   (100.0, 280.0),
    "phone":        (100.0, 280.0),
    "laptop":       (800.0, 4000.0),
    "headphones":   (100.0, 600.0),
    "headphone":    (100.0, 600.0),
    "backpack":     (300.0, 2000.0),
    "wallet":       (30.0,  250.0),
    "sunglasses":   (15.0,  80.0),
    "sunglass":     (15.0,  80.0),
}

# Weight unit → grams conversion factors
_UNIT_TO_GRAMS: dict[str, float] = {
    "g":         1.0,
    "gram":      1.0,
    "grams":     1.0,
    "kg":        1000.0,
    "kilogram":  1000.0,
    "kilograms": 1000.0,
    "oz":        28.3495,
    "ounce":     28.3495,
    "ounces":    28.3495,
    "lb":        453.592,
    "lbs":       453.592,
    "pound":     453.592,
    "pounds":    453.592,
}

# Matches "320g", "1.2 kg", "11 oz", "0.5 pounds", etc.
_WEIGHT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(g|gram|grams|kg|kilogram|kilograms|oz|ounce|ounces|lb|lbs|pound|pounds)\b",
    re.IGNORECASE,
)


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class OfferSignals:
    """All Session 1 signals computed for a single offer."""

    offer_id: str

    # Signal 1 — Price Z-score
    price_zscore: float | None = None
    price_anomaly: bool = False   # True if z < -2.0 (cheap) or z > 3.0 (expensive)

    # Signal 2 — Replica keyword sweep
    replica_flag: bool = False
    matched_keywords: list[str] = field(default_factory=list)

    # Signal 3 — Brand-metadata consistency
    vision_brand: str | None = None    # normalised brand from VisionAgent
    listing_brand: str | None = None   # normalised brand from offer.raw_attributes
    brand_mismatch: bool = False
    brand_check_possible: bool = False

    # Signal 4 — Dimensional / weight anomaly
    weight_grams: float | None = None
    weight_norm_min: float | None = None
    weight_norm_max: float | None = None
    weight_anomaly: bool = False
    weight_check_possible: bool = False

    # Composite risk
    risk_score: float = 0.0            # active / possible  (0.0 → 1.0)
    active_risk_flags: list[str] = field(default_factory=list)


@dataclass
class Session1Result:
    """Aggregate output of Session 1 for the full offer batch."""

    signals: list[OfferSignals]
    batch_mean_price: float
    batch_stdev_price: float
    currency: str              # dominant currency used for Z-score stats


# ── Public entry point ────────────────────────────────────────────────────────

def run_session1(
    offers: list[Any],
    vision_attributes: dict,
) -> Session1Result:
    """
    Compute deterministic heuristic signals for every offer in the batch.

    Parameters
    ----------
    offers:
        list[Offer] — sourced product listings from one source (ebay or serpapi).
    vision_attributes:
        dict — from VisionSuccess.detected_attributes.
        Expected keys (all optional): brand, category, color, material, style.

    Returns
    -------
    Session1Result with one OfferSignals per offer and batch price stats.
    """
    if not offers:
        return Session1Result(
            signals=[],
            batch_mean_price=0.0,
            batch_stdev_price=0.0,
            currency="USD",
        )

    # ── Batch price statistics (Signal 1 setup) ───────────────────────────────
    dominant_currency, prices = _get_price_batch(offers)
    batch_mean, batch_stdev = _compute_price_stats(prices)

    # ── Normalise vision metadata ─────────────────────────────────────────────
    vision_brand = _normalise(vision_attributes.get("brand", ""))
    category     = _normalise(vision_attributes.get("category", ""))

    # ── Per-offer signals ─────────────────────────────────────────────────────
    signals: list[OfferSignals] = []

    for offer in offers:
        sig = OfferSignals(offer_id=offer.offer_id)

        # ── 1. Price Z-score ──────────────────────────────────────────────────
        if (
            offer.price.currency == dominant_currency
            and len(prices) >= 2
            and batch_stdev > 0
        ):
            price_val = float(offer.price.amount)
            sig.price_zscore = (price_val - batch_mean) / batch_stdev
            sig.price_anomaly = (
                sig.price_zscore < -2.0 or sig.price_zscore > 3.0
            )

        # ── 2. Replica keyword sweep ──────────────────────────────────────────
        text = f"{offer.title} {offer.description or ''}".strip()
        sig.replica_flag, sig.matched_keywords = _replica_sweep(text)

        # ── 3. Brand-metadata consistency ─────────────────────────────────────
        listing_brand = _extract_listing_brand(offer.raw_attributes)
        sig.vision_brand   = vision_brand or None
        sig.listing_brand  = listing_brand or None

        if vision_brand and listing_brand:
            sig.brand_check_possible = True
            # Mismatch: neither string contains the other as a substring
            sig.brand_mismatch = (
                vision_brand not in listing_brand
                and listing_brand not in vision_brand
            )
        else:
            sig.brand_check_possible = False

        # ── 4. Dimensional / weight anomaly ───────────────────────────────────
        weight_g = _extract_weight_grams(offer.raw_attributes)
        sig.weight_grams = weight_g

        if weight_g is not None and category:
            norm = _lookup_weight_norm(category)
            if norm:
                sig.weight_norm_min, sig.weight_norm_max = norm
                sig.weight_check_possible = True
                sig.weight_anomaly = weight_g < norm[0] or weight_g > norm[1]
            else:
                sig.weight_check_possible = False
        else:
            sig.weight_check_possible = False

        # ── Composite risk score ──────────────────────────────────────────────
        sig.risk_score, sig.active_risk_flags = _compute_risk_score(sig)

        signals.append(sig)

    return Session1Result(
        signals=signals,
        batch_mean_price=round(batch_mean, 4),
        batch_stdev_price=round(batch_stdev, 4),
        currency=dominant_currency,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _normalise(s: str | None) -> str:
    """Lowercase + strip whitespace; returns '' for None/empty."""
    return (s or "").strip().lower()


def _get_price_batch(offers: list[Any]) -> tuple[str, list[float]]:
    """Return the dominant currency and its price list."""
    currency_counts: Counter = Counter(o.price.currency for o in offers)
    dominant = currency_counts.most_common(1)[0][0]
    prices = [
        float(o.price.amount)
        for o in offers
        if o.price.currency == dominant
    ]
    return dominant, prices


def _compute_price_stats(prices: list[float]) -> tuple[float, float]:
    """Return (mean, sample_stdev) for a list of prices."""
    if not prices:
        return 0.0, 0.0
    n = len(prices)
    mean = sum(prices) / n
    if n < 2:
        return mean, 0.0
    variance = sum((p - mean) ** 2 for p in prices) / (n - 1)
    return mean, math.sqrt(variance)


def _replica_sweep(text: str) -> tuple[bool, list[str]]:
    """Return (flagged, matched_patterns) for a title+description string."""
    matched = [p.pattern for p in _REPLICA_PATTERNS if p.search(text)]
    return bool(matched), matched


def _extract_listing_brand(raw: dict) -> str:
    """Extract and normalise a brand/manufacturer field from raw_attributes."""
    for key in ("brand", "Brand", "manufacturer", "Manufacturer", "make", "Make"):
        val = raw.get(key, "")
        if val and isinstance(val, str) and val.strip():
            return val.strip().lower()
    return ""


def _extract_weight_grams(raw: dict) -> float | None:
    """
    Try to parse a weight value from raw_attributes["weight"] or ["Weight"].
    Returns the weight in grams, or None if not parseable.
    """
    for key in ("weight", "Weight"):
        val = raw.get(key)
        if val is None:
            continue
        m = _WEIGHT_RE.search(str(val))
        if m:
            amount = float(m.group(1))
            unit   = m.group(2).lower()
            factor = _UNIT_TO_GRAMS.get(unit, 1.0)
            return round(amount * factor, 4)
    return None


def _lookup_weight_norm(category: str) -> tuple[float, float] | None:
    """Return (min_g, max_g) for a category, or None if unknown."""
    for key, norm in _WEIGHT_NORMS.items():
        if key in category:
            return norm
    return None


def _compute_risk_score(sig: OfferSignals) -> tuple[float, list[str]]:
    """
    Composite risk = active_flags / possible_checks.

    A signal only counts as "possible" if we have enough data to evaluate it.
    """
    active: list[str] = []
    possible = 0

    # Price anomaly — checkable when we had ≥2 offers in the same currency
    if sig.price_zscore is not None:
        possible += 1
        if sig.price_anomaly:
            active.append("price_anomaly")

    # Replica keyword — always checkable (text is always available)
    possible += 1
    if sig.replica_flag:
        active.append("replica_keyword")

    # Brand mismatch — only when both brands are known
    if sig.brand_check_possible:
        possible += 1
        if sig.brand_mismatch:
            active.append("brand_mismatch")

    # Weight anomaly — only when weight + category norm are known
    if sig.weight_check_possible:
        possible += 1
        if sig.weight_anomaly:
            active.append("weight_anomaly")

    if possible == 0:
        return 0.0, []

    return round(len(active) / possible, 4), active
