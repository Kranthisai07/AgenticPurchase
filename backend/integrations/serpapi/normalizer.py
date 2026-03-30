"""
SerpApi ShoppingResult → Offer normalizer.

SerpApi Google Shopping response fields relevant here:
  title           str   — listing title
  extracted_price float — numeric price (preferred over "price" string)
  price           str   — price string fallback e.g. "$29.99"
  currency        str   — currency code; "$" prefix treated as "USD"
  source          str   — seller / merchant name
  link            str   — product page URL
  product_link    str   — alternate product URL (fallback)
  thumbnail       str   — image URL
  position        int   — rank in SerpApi results
  rating          float — seller/product rating (0-5)
  reviews         int   — review count
  product_id      str   — SerpApi product identifier

  free_delivery   bool  — present in some SerpApi plans; True when free delivery offered
  shipping        str   — shipping description e.g. "Free delivery", "$4.99 shipping"
                          checked when free_delivery is absent

  condition       str   — item condition string when provided by the merchant
                          e.g. "New", "Used", "Refurbished"
  item_condition  str   — alternate condition field name used by some SerpApi engines

If free_delivery / shipping / condition are absent the normalizer falls back to
the previous conservative defaults (free_shipping=False, condition="new").
"""
import uuid
from typing import Any

from backend.core.logging import get_logger
from backend.models.common import Money
from backend.models.offer import Offer

logger = get_logger(__name__)

# Condition strings from SerpApi mapped to the system's internal enum values.
_CONDITION_MAP: dict[str, str] = {
    "new":          "new",
    "used":         "used",
    "refurbished":  "refurbished",
    "renewed":      "refurbished",
    "open box":     "used",
}


def _extract_free_shipping(raw: dict[str, Any]) -> bool:
    """
    Attempt to detect free shipping from SerpApi response fields.

    Checks (in order):
      1. "free_delivery" boolean field — set by SerpApi when merchant signals free delivery.
      2. "shipping" string field — scanned for the word "free" case-insensitively.

    Returns False (conservative default) when neither field is present.
    """
    free_delivery = raw.get("free_delivery")
    if free_delivery is not None:
        return bool(free_delivery)

    shipping_str = raw.get("shipping", "")
    if shipping_str:
        return "free" in str(shipping_str).lower()

    logger.debug("serpapi.normalizer.free_shipping_field_absent", title=raw.get("title", ""))
    return False


def _extract_condition(raw: dict[str, Any]) -> str:
    """
    Attempt to extract item condition from SerpApi response fields.

    Checks "condition" then "item_condition". Maps known strings to the
    system's internal values: "new", "used", "refurbished".
    Unmapped or absent values fall back to "new" (conservative default,
    as Google Shopping results are predominantly new items).
    """
    for field in ("condition", "item_condition"):
        value = raw.get(field)
        if value:
            normalised = _CONDITION_MAP.get(str(value).lower().strip())
            if normalised:
                return normalised
            logger.debug(
                "serpapi.normalizer.unknown_condition",
                raw_condition=value,
                title=raw.get("title", ""),
            )
            return "new"

    logger.debug("serpapi.normalizer.condition_field_absent", title=raw.get("title", ""))
    return "new"  # Google Shopping predominantly lists new items


def normalize_serpapi_result(raw: dict[str, Any]) -> Offer:
    price_str = raw.get("extracted_price", raw.get("price", "0"))
    try:
        price_float = float(str(price_str).replace("$", "").replace(",", ""))
    except (ValueError, TypeError):
        price_float = 0.0

    currency = raw.get("currency", "USD")
    if currency.startswith("$"):
        currency = "USD"

    seller = raw.get("source", "Unknown")
    thumbnail = raw.get("thumbnail", "")
    images = [thumbnail] if thumbnail else []

    return Offer(
        offer_id=str(uuid.uuid4()),
        source="serpapi",
        title=raw.get("title", ""),
        description=None,
        price=Money(amount=price_float, currency=currency),
        url=raw.get("link", raw.get("product_link", "")),
        image_urls=images,
        seller_id=seller,
        seller_name=seller,
        free_shipping=_extract_free_shipping(raw),
        estimated_delivery_days=None,
        condition=_extract_condition(raw),
        raw_attributes={
            "position": raw.get("position"),
            "rating": raw.get("rating"),
            "reviews": raw.get("reviews"),
            "product_id": raw.get("product_id"),
        },
    )


def normalize_serpapi_results(raw_list: list[dict[str, Any]]) -> list[Offer]:
    offers = []
    for raw in raw_list:
        try:
            offers.append(normalize_serpapi_result(raw))
        except Exception:
            continue
    return offers
