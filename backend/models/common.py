from pydantic import BaseModel, field_validator


class Address(BaseModel):
    name: str
    line1: str
    line2: str | None = None
    city: str
    state: str
    postal_code: str
    country: str  # ISO 3166-1 alpha-2

    @field_validator("country")
    @classmethod
    def country_must_be_two_chars(cls, v: str) -> str:
        if len(v) != 2:
            raise ValueError("country must be a 2-character ISO 3166-1 alpha-2 code")
        return v.upper()


class Money(BaseModel):
    amount: float
    currency: str  # ISO 4217

    @field_validator("currency")
    @classmethod
    def currency_must_be_three_chars(cls, v: str) -> str:
        if len(v) != 3:
            raise ValueError("currency must be a 3-character ISO 4217 code")
        return v.upper()
