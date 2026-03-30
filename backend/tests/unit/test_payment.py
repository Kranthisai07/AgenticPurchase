from ...libs.utils.payment import luhn_check, validate_expiry, validate_cvv, idempotency_key

def test_luhn_valid():
    assert luhn_check("4242424242424242")

def test_luhn_invalid():
    assert not luhn_check("4242424242424241")

def test_expiry_and_cvv():
    assert validate_expiry("12/29")
    assert not validate_expiry("13/29")
    assert validate_cvv("123")
    assert not validate_cvv("12a")

def test_idempotency():
    a = idempotency_key("hello")
    b = idempotency_key("hello")
    c = idempotency_key("world")
    assert a == b and a != c
