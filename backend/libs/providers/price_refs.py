from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Tuple

from ..schemas.models import Offer


PRICE_REFS_PATH = os.getenv(
    "PRICE_REFS_JSON",
    str(Path(__file__).resolve().parents[2] / "data" / "price_refs.json"),
)


@lru_cache(maxsize=1)
def _load_price_refs() -> Dict[str, Dict[str, float]]:
    path = Path(PRICE_REFS_PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _key(brand: str | None, category: str | None) -> Tuple[str, str]:
    return ((brand or "").strip().lower(), (category or "").strip().lower())


def _extract_brand_from_title(title: str) -> str | None:
    if not title:
        return None
    # Heuristic: first token or known brand prefix
    tok = title.strip().split()[0].strip().strip("-_")
    if not tok:
        return None
    return tok


def compute_price_z(offer: Offer) -> float | None:
    """Compute price z-score using precomputed brand/category medians and MAD/IQR.

    Returns negative z for cheaper-than-reference, positive for expensive listings.
    If refs are missing, returns None.
    """
    refs = _load_price_refs()
    if not refs:
        return None
    brand = _extract_brand_from_title(offer.title or "")
    cat = offer.category or None
    price = offer.price_usd
    if price is None:
        return None
    # Try brand+category, then brand-only, then category-only, then global
    for key in (
        f"{(brand or '').lower()}|{(cat or '').lower()}",
        f"{(brand or '').lower()}|",
        f"|{(cat or '').lower()}",
        "|",
    ):
        stats = refs.get(key)
        if not stats:
            continue
        metric_stats = stats.get("price") or stats
        median = float(metric_stats.get("median", 0.0))
        spread = float(metric_stats.get("spread", 0.0)) or 1.0
        # robust z (median-centered spread): (x - median) / spread
        return (float(price) - median) / spread
    return None


def _compute_metric_z(offer: Offer, metric: str, attr_name: str) -> float | None:
    refs = _load_price_refs()
    if not refs:
        return None
    brand = _extract_brand_from_title(offer.title or "")
    cat = offer.category or None
    value = None
    if metric == "price":
        value = offer.price_usd
    else:
        attrs = offer.attributes or {}
        raw = attrs.get(attr_name)
        if raw is None:
            return None
        try:
            value = float(raw)
        except Exception:
            return None
    if value is None:
        return None
    for key in (
        f"{(brand or '').lower()}|{(cat or '').lower()}",
        f"{(brand or '').lower()}|",
        f"|{(cat or '').lower()}",
        "|",
    ):
        stats = refs.get(key)
        if not stats:
            continue
        metric_stats = stats.get(metric)
        if not metric_stats:
            continue
        median = float(metric_stats.get("median", 0.0))
        spread = float(metric_stats.get("spread", 0.0)) or 1.0
        return (float(value) - median) / spread
    return None


def compute_weight_z(offer: Offer) -> float | None:
    return _compute_metric_z(offer, "weight", "weight")


def compute_dimension_zscores(offer: Offer) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for metric in ("height", "width", "length"):
        z = _compute_metric_z(offer, metric, metric)
        if z is not None:
            scores[metric] = z
    return scores
