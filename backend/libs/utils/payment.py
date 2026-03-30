import hashlib
import re
from datetime import datetime


def luhn_check(card_number: str) -> bool:
    digits = [int(c) for c in card_number if c.isdigit()]
    if not digits:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def validate_expiry(exp: str) -> bool:
    return bool(re.fullmatch(r"(0[1-9]|1[0-2])/\d{2}", exp))


def expiry_is_future(exp: str, reference: datetime | None = None) -> bool:
    if not validate_expiry(exp):
        return False
    reference = reference or datetime.utcnow()
    month_str, year_str = exp.split("/")
    month = int(month_str)
    year = 2000 + int(year_str)
    if year > reference.year:
        return True
    if year < reference.year:
        return False
    return month >= reference.month


def validate_cvv(cvv: str) -> bool:
    return bool(re.fullmatch(r"\d{3}", cvv))


def idempotency_key(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
