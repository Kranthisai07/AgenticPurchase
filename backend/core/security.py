import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

import jwt
import stripe

from backend.core.config import get_settings
from backend.core.exceptions import ConfigurationError
from backend.core.logging import get_logger

logger = get_logger(__name__)


def generate_api_key() -> str:
    """Generate a secure random API key."""
    return secrets.token_urlsafe(48)


def verify_api_key(provided: str, expected: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    return hmac.compare_digest(provided.encode(), expected.encode())


# ── Stripe webhook verification ───────────────────────────────────────────────

def verify_stripe_webhook(
    payload: bytes,
    sig_header: str,
) -> stripe.Event:
    """
    Verify Stripe webhook HMAC-SHA256 signature and return a typed stripe.Event.

    Raises ValueError on:
      - missing Stripe-Signature header
      - signature mismatch
      - missing STRIPE_WEBHOOK_SECRET configuration

    Logging of invalid-signature events is intentionally delegated to the
    caller (the route handler) so the HTTP context is available.
    """
    if not sig_header:
        raise ValueError("Missing Stripe-Signature header")

    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise ConfigurationError("STRIPE_WEBHOOK_SECRET is not configured")

    try:
        return stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.stripe_webhook_secret,
        )
    except stripe.error.SignatureVerificationError as e:
        logger.warning(
            "security_event",
            event_type="webhook_signature_invalid",
            saga_id="unknown",
            detail="HMAC mismatch on incoming webhook",
            source_module="security",
        )
        raise ValueError(f"Invalid Stripe signature: {e}") from e


# ── JWT session tokens (C-02) ─────────────────────────────────────────────────

def create_session_token(
    user_id: str,
    session_id: str,
) -> str:
    """
    Create a signed JWT for a session.

    Claims:
      sub  — user_id (subject)
      jti  — session_id (JWT ID, used as DB key)
      iat  — issued-at timestamp
      exp  — expiry timestamp (now + JWT_EXPIRY_HOURS)
    """
    settings = get_settings()
    payload = {
        "sub": user_id,
        "jti": session_id,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_session_token(token: str) -> dict:
    """
    Decode and verify a signed JWT.

    Returns the full claims dict on success.
    Raises ValueError on expiry or any token invalidity.
    """
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise ValueError("Session expired")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid session token: {e}") from e


# ── Idempotency key generation ────────────────────────────────────────────────

def generate_checkout_idempotency_key(
    saga_id: str,
    offer_id: str,
    user_id: str,
) -> str:
    """Deterministic idempotency key: SHA256(saga_id + offer_id + user_id)."""
    raw = f"{saga_id}:{offer_id}:{user_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Request ID ────────────────────────────────────────────────────────────────

def generate_request_id() -> str:
    return secrets.token_hex(16)
