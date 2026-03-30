"""
Prometheus metrics registry.
All metrics defined here — imported where needed.
Never create metrics inside functions (duplicates on reload).

Note on agent_duration_seconds:
  backend/core/telemetry.py already registers a Histogram named
  "agent_duration_seconds".  Registering a second collector with the
  same name raises a ValueError at import time.  AGENT_DURATION is
  therefore aliased from telemetry rather than re-created here.
"""
from prometheus_client import Counter, Histogram

# ── Saga metrics ──────────────────────────────────────────────────────────────

SAGA_STARTED = Counter(
    "saga_started_total",
    "Total sagas started",
    ["session_type"],           # future: guest vs logged_in
)

SAGA_COMPLETED = Counter(
    "saga_completed_total",
    "Total sagas completed successfully",
)

SAGA_FAILED = Counter(
    "saga_failed_total",
    "Total sagas failed",
    ["reason"],                 # timeout, no_results, payment_failed, error
)

SAGA_DURATION = Histogram(
    "saga_duration_seconds",
    "End-to-end saga duration from start to completion",
    buckets=[5, 10, 20, 30, 45, 60, 90, 120],
)

# ── Agent metrics ─────────────────────────────────────────────────────────────

# agent_duration_seconds is already registered in backend/core/telemetry.py.
# Re-using the existing Histogram to avoid duplicate timeseries errors.
from backend.core.telemetry import agent_duration_seconds as AGENT_DURATION  # noqa: E402

AGENT_SUCCESS = Counter(
    "agent_success_total",
    "Agent executions that returned status=success",
    ["agent_type"],
)

AGENT_FAILURE = Counter(
    "agent_failure_total",
    "Agent executions that returned status=failure",
    ["agent_type", "error_code"],
)

AGENT_TIMEOUT = Counter(
    "agent_timeout_total",
    "Agent executions that hit timeout",
    ["agent_type"],
)

# ── Checkout metrics ──────────────────────────────────────────────────────────

CHECKOUT_ATTEMPTED = Counter(
    "checkout_attempted_total",
    "Checkout attempts initiated",
)

CHECKOUT_SUCCEEDED = Counter(
    "checkout_succeeded_total",
    "Successful checkouts confirmed via webhook",
)

CHECKOUT_FAILED = Counter(
    "checkout_failed_total",
    "Failed checkouts",
    ["reason"],                 # declined, velocity_limit, stripe_error
)

# ── Security metrics ──────────────────────────────────────────────────────────

INJECTION_BLOCKED = Counter(
    "injection_blocked_total",
    "Prompt injection attempts blocked",
    ["context"],                # user_input, clarification_response, vision_output
)

RATE_LIMIT_HIT = Counter(
    "rate_limit_hit_total",
    "Rate limit rejections",
    ["endpoint"],
)

VELOCITY_LIMIT_HIT = Counter(
    "velocity_limit_hit_total",
    "Checkout velocity limit rejections",
)
