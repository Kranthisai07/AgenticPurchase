import json
import os
from typing import Dict

from ...libs.schemas.models import PaymentInput, Receipt, Offer
from ...libs.utils.payment import (
    expiry_is_future,
    idempotency_key,
    luhn_check,
    validate_cvv,
    validate_expiry,
)

_MAX_AMOUNT = float(os.getenv("CHECKOUT_MAX_AMOUNT", "5000"))
_BLACKLISTED_VENDORS = {"FraudCo", "ScamSupply", "UnknownMart"}

_RECEIPT_STORE: Dict[str, Receipt] = {}
_CARD_ACTIVITY: Dict[str, int] = {}


def _digits(card_number: str) -> str:
    return "".join(ch for ch in card_number if ch.isdigit())


def _detect_card_type(card_number: str) -> str:
    digits = card_number
    if digits.startswith("4"):
        return "visa"
    if any(digits.startswith(prefix) for prefix in ["51", "52", "53", "54", "55"]):
        return "mastercard"
    if digits.startswith("34") or digits.startswith("37"):
        return "amex"
    if digits.startswith("6"):
        return "discover"
    return "unknown"


def _mask_card(card_number: str) -> str:
    return f"{'*' * (len(card_number) - 4)}{card_number[-4:]}"


def _validate_offer(offer: Offer) -> None:
    if offer.price_usd <= 0:
        raise ValueError("Invalid offer amount")
    if offer.price_usd > _MAX_AMOUNT:
        raise ValueError("Amount exceeds checkout limit")
    if offer.vendor in _BLACKLISTED_VENDORS:
        raise ValueError("Vendor not allowed")


def _check_card_velocity(card: str) -> None:
    attempts = _CARD_ACTIVITY.get(card, 0)
    if attempts > 5:
        raise ValueError("Card flagged for excessive failed attempts")


def _validate_card_length(card: str, card_brand: str) -> None:
    length = len(card)
    if card_brand == "amex" and length != 15:
        raise ValueError("Invalid card")
    if card_brand in {"visa", "mastercard", "discover"} and length != 16:
        raise ValueError("Invalid card")
    if card_brand == "unknown" and not (13 <= length <= 19):
        raise ValueError("Invalid card")


async def pay(offer: Offer, payment: PaymentInput, idem_key: str) -> Receipt:
    _validate_offer(offer)

    digits = _digits(payment.card_number)
    if len(digits) < 13:
        raise ValueError("Card number too short")
    payment.card_number = digits

    card_brand = _detect_card_type(digits)
    _validate_card_length(digits, card_brand)
    _check_card_velocity(digits)

    if not validate_expiry(payment.expiry_mm_yy):
        _CARD_ACTIVITY[digits] = _CARD_ACTIVITY.get(digits, 0) + 1
        raise ValueError("Invalid expiry")
    if not expiry_is_future(payment.expiry_mm_yy):
        _CARD_ACTIVITY[digits] = _CARD_ACTIVITY.get(digits, 0) + 1
        raise ValueError("Card expired")

    if not luhn_check(digits):
        _CARD_ACTIVITY[digits] = _CARD_ACTIVITY.get(digits, 0) + 1
        raise ValueError("Invalid card")
    if not validate_cvv(payment.cvv):
        _CARD_ACTIVITY[digits] = _CARD_ACTIVITY.get(digits, 0) + 1
        raise ValueError("Invalid CVV")

    _CARD_ACTIVITY[digits] = 0

    masked = _mask_card(digits)
    payload = json.dumps(
        {
            "vendor": offer.vendor,
            "title": offer.title,
            "amount": offer.price_usd,
            "card": masked,
            "card_type": card_brand,
        },
        sort_keys=True,
    )
    calc_key = idempotency_key(payload)
    idem_key = idem_key or calc_key
    if idem_key in _RECEIPT_STORE:
        return _RECEIPT_STORE[idem_key]

    receipt = Receipt(
        order_id=calc_key[:12],
        idempotency_key=idem_key,
        amount_usd=offer.price_usd,
        vendor=offer.vendor,
        card_brand=card_brand,
        masked_card=masked,
    )
    _RECEIPT_STORE[idem_key] = receipt
    return receipt
