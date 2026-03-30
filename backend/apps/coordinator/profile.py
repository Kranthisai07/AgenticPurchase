from __future__ import annotations

from ...libs.schemas.models import (
    Address,
    CheckoutProfile,
    PaymentMethod,
    ShippingOption,
)

DEFAULT_CHECKOUT_PROFILE = CheckoutProfile(
    address=Address(
        name="Ada Lovelace",
        line1="1254 Chat Road",
        line2=None,
        city="San Francisco",
        state="CA",
        postal_code="94131",
        country="USA",
        phone="+1 (415) 555-1254",
    ),
    payment=PaymentMethod(
        brand="visa",
        last4="4242",
        expiry_month=12,
        expiry_year=2029,
    ),
    shipping=ShippingOption(
        carrier="USPS",
        service="Ground Advantage",
        eta_business_days=3,
        cost_usd=0.0,
    ),
)
