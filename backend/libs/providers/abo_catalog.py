from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from ..schemas.models import Offer, PurchaseIntent


ABO_OFFERS_PATH = os.getenv(
    "ABO_OFFERS_JSONL",
    str(Path(__file__).resolve().parents[2] / "data" / "abo_offers.jsonl"),
)


@lru_cache(maxsize=1)
def _load_offers() -> List[Dict[str, Any]]:
    path = Path(ABO_OFFERS_PATH)
    if not path.exists():
        return []
    offers: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            data = json.loads(line)
            if isinstance(data, dict):
                offers.append(data)
    return offers


def _tokens(text: str) -> List[str]:
    return [tok for tok in re.split(r"[^a-z0-9]+", text.lower()) if tok]


def _is_phone_like(pi: PurchaseIntent) -> bool:
    tokens = _tokens(pi.item_name or "")
    phone_markers = {"phone", "iphone", "samsung", "pixel", "oneplus", "xiaomi", "redmi"}
    accessory_markers = {"case", "cover", "bumper", "sleeve"}
    return bool(tokens & phone_markers) and not bool(tokens & accessory_markers)


def _is_accessory(offer: Dict[str, Any]) -> bool:
    text = " ".join(
        [
          offer.get("title") or "",
          " ".join(offer.get("keywords") or []),
          offer.get("category") or "",
        ]
    ).lower()
    return any(term in text for term in ["case", "cover", "bumper", "sleeve", "screen protector"])


def search_abo_offers(pi: PurchaseIntent, top_k: int = 8) -> List[Dict[str, Any]]:
    offers = _load_offers()
    if not offers:
        return []
    q_tokens = set(_tokens(pi.item_name or ""))
    brand = (pi.brand or "").lower()
    color = (pi.color or "").lower()
    phone_like = _is_phone_like(pi)

    scored: List[tuple[float, Dict[str, Any]]] = []
    for offer in offers:
        if phone_like and _is_accessory(offer):
            # skip cases/covers when the query is for a phone device, not an accessory
            continue
        score = 0.0
        title_tokens = set(_tokens(offer.get("title") or ""))
        if q_tokens:
            score += len(q_tokens & title_tokens)
        for kw in offer.get("keywords") or []:
            score += len(q_tokens & set(_tokens(kw))) * 0.2
        vendor = (offer.get("vendor") or "").lower()
        if brand and brand in vendor:
            score += 2.0
        if color and color in (offer.get("title") or "").lower():
            score += 0.5
        price = offer.get("price_usd")
        if pi.budget_usd and price and price <= pi.budget_usd:
            score += 0.5
        scored.append((score, offer))

    scored.sort(key=lambda tup: tup[0], reverse=True)
    top = [offer for score, offer in scored if score > 0][:top_k]
    if not top:
        top = [offer for _, offer in scored[:top_k]]
    return top
