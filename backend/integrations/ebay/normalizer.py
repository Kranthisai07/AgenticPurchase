"""
EbayItem → Offer normalizer.
"""
import uuid
from typing import Any

from backend.models.common import Money
from backend.models.offer import Offer

CONDITION_MAP = {
    "NEW": "new",
    "LIKE_NEW": "used",
    "GOOD": "used",
    "ACCEPTABLE": "used",
    "FOR_PARTS_OR_NOT_WORKING": "used",
    "MANUFACTURER_REFURBISHED": "refurbished",
    "SELLER_REFURBISHED": "refurbished",
}


def normalize_ebay_item(raw: dict[str, Any]) -> Offer:
    price_data = raw.get("price", {})
    price_float = float(price_data.get("value", 0))
    currency = price_data.get("currency", "USD")

    # Shipping
    shipping_options = raw.get("shippingOptions", [])
    free_shipping = False
    if shipping_options:
        shipping_cost = shipping_options[0].get("shippingCost", {})
        free_shipping = float(shipping_cost.get("value", 1)) == 0.0

    images = raw.get("image", {})
    image_url = images.get("imageUrl", "")
    additional_images = [i.get("imageUrl", "") for i in raw.get("additionalImages", [])]
    all_images = [image_url] + additional_images if image_url else additional_images

    raw_condition = raw.get("condition", "UNKNOWN").upper()
    condition = CONDITION_MAP.get(raw_condition, "unknown")

    seller = raw.get("seller", {})
    seller_id = seller.get("username", str(raw.get("itemId", "")))
    seller_name = seller.get("username", seller_id)

    return Offer(
        offer_id=str(uuid.uuid4()),
        source="ebay",
        title=raw.get("title", ""),
        description=None,  # eBay Browse API doesn't include full description in search
        price=Money(amount=price_float, currency=currency),
        url=raw.get("itemWebUrl", ""),
        image_urls=[u for u in all_images if u],
        seller_id=seller_id,
        seller_name=seller_name,
        free_shipping=free_shipping,
        estimated_delivery_days=None,
        condition=condition,
        raw_attributes={
            "item_id": raw.get("itemId"),
            "category_id": raw.get("categoryId"),
            "top_rated": raw.get("topRatedBuyingExperience", False),
            "buying_options": raw.get("buyingOptions", []),
        },
    )


def normalize_ebay_items(raw_list: list[dict[str, Any]]) -> list[Offer]:
    offers = []
    for raw in raw_list:
        try:
            offers.append(normalize_ebay_item(raw))
        except Exception:
            continue
    return offers
