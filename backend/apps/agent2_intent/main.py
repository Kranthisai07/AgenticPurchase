from __future__ import annotations

import logging
import os
import re
from typing import Optional

from ...libs.agents.intent_chain import run_intent_chain
from ...libs.schemas.models import PurchaseIntent, ProductHypothesis

CHOICES = {
    "same_bottle": "same_bottle",
    "different_color": "different_color",
    "different_bottle_same_brand": "different_bottle_same_brand",
}

COLOR_VOCAB = [
    "black",
    "white",
    "blue",
    "red",
    "green",
    "yellow",
    "pink",
    "purple",
    "grey",
    "gray",
    "orange",
    "silver",
    "gold",
]
SIZE_VOCAB = ["s", "m", "l", "xl"]

logger = logging.getLogger(__name__)


def _item_display(hypo: ProductHypothesis) -> str:
    return (hypo.display_name or hypo.label or "item").strip()


def _extract_qty(text: str) -> int:
    lowered = text.lower()
    m = re.search(r"(\d+)\s*(qty|quantity|units?)", lowered)
    if m:
        return int(m.group(1))
    compact = re.search(r"(qty|quantity)\s*[:\-]?\s*(\d+)", lowered)
    if compact:
        return int(compact.group(2))
    number = re.search(r"\b(\d+)\b", text)
    return int(number.group(1)) if number else 1


def _extract_budget(text: str) -> Optional[float]:
    normalized = text.lower()
    patterns = [
        r"(?:budget|under|below|less than)\s*\$?\s*(\d+(?:\.\d{1,2})?)",
        r"\$\s*(\d+(?:\.\d{1,2})?)",
        r"(\d+(?:\.\d{1,2})?)\s*usd",
    ]
    for pattern in patterns:
        m = re.search(pattern, normalized)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def propose_options(hypo: ProductHypothesis) -> dict:
    display = _item_display(hypo)
    category = hypo.category or hypo.item_type

    if not category and (hypo.label or "object").lower() == "object":
        prompt = (
            "I couldn't confidently detect a supported product. "
            "Try another angle or tell me what you're looking for (e.g., 'need a blue pen')."
        )
        return {"prompt": prompt, "options": [], "suggested_inputs": {}}

    brand = hypo.brand or "the detected brand"
    color = hypo.color or "the detected color"

    prompt = (
        f"Is this the item you want to purchase? ({display}) "
        f"I detected {('a ' + color + ' ') if hypo.color else ''}{display}"
        f"{(' from ' + brand) if hypo.brand else ''}. Choose one:"
    ).strip()

    options = [
        {"key": CHOICES["same_bottle"], "label": f"Same {display}"},
        {"key": CHOICES["different_color"], "label": "Different color"},
        {
            "key": CHOICES["different_bottle_same_brand"],
            "label": f"Different {display} ({brand if hypo.brand else 'same brand'})",
        },
    ]

    suggested_inputs = {
        CHOICES["same_bottle"]: f"same {display}",
        CHOICES["different_color"]: f"different color {display}",
        CHOICES["different_bottle_same_brand"]: (
            f"different {display} same brand {brand}" if hypo.brand else f"different {display} same brand"
        ),
    }

    return {"prompt": prompt, "options": options, "suggested_inputs": suggested_inputs}


def confirm_from_choice(
    hypo: ProductHypothesis,
    choice_key: str,
    *,
    color_hint: Optional[str] = None,
    qty: Optional[int] = None,
    budget: Optional[float] = None,
) -> PurchaseIntent:
    item = _item_display(hypo)
    brand = hypo.brand
    size = None
    quantity = qty or 1
    category = hypo.category or hypo.item_type

    if choice_key == CHOICES["same_bottle"]:
        return PurchaseIntent(
            item_name=item,
            color=hypo.color,
            size=size,
            quantity=quantity,
            budget_usd=budget,
            brand=brand,
            category=category,
        )

    if choice_key == CHOICES["different_color"]:
        return PurchaseIntent(
            item_name=item,
            color=(color_hint or None),
            size=size,
            quantity=quantity,
            budget_usd=budget,
            brand=brand,
            category=category,
        )

    if choice_key == CHOICES["different_bottle_same_brand"]:
        name = f"{brand} {item}" if brand else item
        return PurchaseIntent(
            item_name=name,
            color=None,
            size=size,
            quantity=quantity,
            budget_usd=budget,
            brand=brand,
            category=category,
        )

    return PurchaseIntent(
        item_name=item,
        color=hypo.color,
        size=size,
        quantity=quantity,
        budget_usd=budget,
        brand=brand,
        category=category,
    )


async def confirm_intent(hypo: ProductHypothesis, user_text: Optional[str] = None) -> PurchaseIntent:
    if _langchain_enabled():
        try:
            return await run_intent_chain(hypo, user_text)
        except Exception as exc:
            logger.warning("LangChain intent fallback triggered: %s", exc, exc_info=True)

    t = (user_text or "").lower().strip()
    qty = _extract_qty(t)
    budget = _extract_budget(t)
    item = _item_display(hypo)
    category = hypo.category or hypo.item_type
    brand = hypo.brand

    if (hypo.label or "object").lower() == "object" and not category:
        color = None
        for c in COLOR_VOCAB:
            if c in t:
                color = c
                break
        return PurchaseIntent(
            item_name=item,
            color=color,
            size=None,
            quantity=qty,
            budget_usd=budget,
            brand=brand,
            category=None,
        )

    if "same" in t and item.lower() in t:
        return confirm_from_choice(hypo, CHOICES["same_bottle"], qty=qty, budget=budget)

    if "same item" in t or "same product" in t or "same one" in t:
        return confirm_from_choice(hypo, CHOICES["same_bottle"], qty=qty, budget=budget)

    if "different color" in t or "other color" in t:
        color_hint = None
        for c in COLOR_VOCAB:
            if re.search(rf"\b{c}\b", t):
                color_hint = c
                break
        return confirm_from_choice(
            hypo,
            CHOICES["different_color"],
            color_hint=color_hint,
            qty=qty,
            budget=budget,
        )

    if "different" in t and "same brand" in t:
        return confirm_from_choice(hypo, CHOICES["different_bottle_same_brand"], qty=qty, budget=budget)

    if "different brand" in t:
        brand = None

    color = None
    for c in COLOR_VOCAB:
        if c in t:
            color = c
            break

    size = None
    for s in SIZE_VOCAB:
        if f" {s} " in f" {t} ":
            size = s.upper()
            break

    return PurchaseIntent(
        item_name=item,
        color=color or hypo.color,
        size=size,
        quantity=qty,
        budget_usd=budget,
        brand=brand,
        category=category,
    )


def _langchain_enabled() -> bool:
    flag = os.getenv("USE_LANGCHAIN_INTENT", os.getenv("USE_LANGCHAIN", "0"))
    return flag is not None and flag.strip().lower() in {"1", "true", "yes"}
