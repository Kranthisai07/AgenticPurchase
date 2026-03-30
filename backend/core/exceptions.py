from typing import Any


class AgenticPurchaseError(Exception):
    """Base exception for all domain errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ── Agent errors ──────────────────────────────────────────────────────────────

class AgentError(AgenticPurchaseError):
    """Raised when an agent encounters an unrecoverable error."""


class AgentTimeoutError(AgentError):
    """Raised when an agent exceeds its allowed execution time."""

    def __init__(self, agent_type: str, timeout_seconds: int) -> None:
        super().__init__(
            f"Agent '{agent_type}' timed out after {timeout_seconds}s",
            {"agent_type": agent_type, "timeout_seconds": timeout_seconds},
        )


class AgentBusError(AgentError):
    """Raised when the AgentBus cannot dispatch a task."""


class SelfEvaluationError(AgentError):
    """Raised when an agent's self-evaluation determines the result is insufficient."""

    def __init__(self, agent_type: str, reason: str) -> None:
        super().__init__(
            f"Agent '{agent_type}' self-evaluation failed: {reason}",
            {"agent_type": agent_type, "reason": reason},
        )


# ── Intent errors ─────────────────────────────────────────────────────────────

class IntentParsingError(AgenticPurchaseError):
    """Raised when intent cannot be parsed from user input."""


class PromptInjectionError(AgenticPurchaseError):
    """Raised when a prompt injection attempt is detected."""

    def __init__(self, risk_score: float) -> None:
        super().__init__(
            f"Prompt injection detected (risk_score={risk_score:.2f})",
            {"risk_score": risk_score},
        )


# ── Sourcing errors ───────────────────────────────────────────────────────────

class SourcingError(AgenticPurchaseError):
    """Base class for sourcing-related errors."""


class VendorAPIError(SourcingError):
    """Raised when a vendor API call fails."""

    def __init__(self, vendor: str, status_code: int | None = None, message: str = "") -> None:
        super().__init__(
            f"Vendor API error for '{vendor}': {message}",
            {"vendor": vendor, "status_code": status_code},
        )


class NoResultsError(SourcingError):
    """Raised when a vendor search returns zero results."""

    def __init__(self, vendor: str, query: str) -> None:
        super().__init__(
            f"No results found on '{vendor}' for query: {query}",
            {"vendor": vendor, "query": query},
        )


# ── Checkout errors ───────────────────────────────────────────────────────────

class CheckoutError(AgenticPurchaseError):
    """Base class for checkout-related errors."""


class PaymentDeclinedError(CheckoutError):
    """Raised when Stripe declines the payment."""

    def __init__(self, decline_code: str = "") -> None:
        super().__init__(
            f"Payment declined: {decline_code}",
            {"decline_code": decline_code},
        )


class VelocityLimitExceededError(CheckoutError):
    """Raised when the user exceeds the checkout attempt rate limit."""

    def __init__(self, user_id: str, limit: int) -> None:
        super().__init__(
            f"Velocity limit exceeded for user '{user_id}' (max {limit}/hour)",
            {"user_id": user_id, "limit": limit},
        )


class IdempotencyConflictError(CheckoutError):
    """Raised when an idempotency key collision is detected."""


# ── Session / Saga errors ─────────────────────────────────────────────────────

class SessionNotFoundError(AgenticPurchaseError):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session '{session_id}' not found", {"session_id": session_id})


class SagaNotFoundError(AgenticPurchaseError):
    def __init__(self, saga_id: str) -> None:
        super().__init__(f"Saga '{saga_id}' not found", {"saga_id": saga_id})


class SagaStateError(AgenticPurchaseError):
    """Raised when a saga operation is invalid for the current state."""


# ── Infrastructure errors ─────────────────────────────────────────────────────

class DatabaseError(AgenticPurchaseError):
    """Raised for unexpected database errors."""


class RedisError(AgenticPurchaseError):
    """Raised for unexpected Redis errors."""


class ConfigurationError(AgenticPurchaseError):
    """Raised when a required configuration value is missing or invalid."""
