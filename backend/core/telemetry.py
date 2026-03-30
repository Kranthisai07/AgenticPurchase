from opentelemetry import trace
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from prometheus_client import Counter, Histogram, start_http_server

from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

# ── Prometheus metrics ────────────────────────────────────────────────────────

agent_invocations_total = Counter(
    "agent_invocations_total",
    "Total agent invocations",
    ["agent_type", "status"],
)

agent_duration_seconds = Histogram(
    "agent_duration_seconds",
    "Agent execution duration in seconds",
    ["agent_type"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0],
)

saga_total = Counter(
    "saga_total",
    "Total sagas initiated",
    ["status"],
)

checkout_attempts_total = Counter(
    "checkout_attempts_total",
    "Total checkout attempts",
    ["status"],
)

sourcing_results_total = Counter(
    "sourcing_results_total",
    "Total sourcing results by vendor",
    ["vendor", "status"],
)

# ── OpenTelemetry ─────────────────────────────────────────────────────────────

_tracer_provider: TracerProvider | None = None


def setup_telemetry() -> None:
    global _tracer_provider

    settings = get_settings()
    resource = Resource(attributes={SERVICE_NAME: "agentic-purchase"})
    _tracer_provider = TracerProvider(resource=resource)

    if settings.is_development:
        _tracer_provider.add_span_processor(
            BatchSpanProcessor(ConsoleSpanExporter())
        )

    trace.set_tracer_provider(_tracer_provider)
    logger.info("telemetry.opentelemetry.configured")


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def record_agent_invocation(agent_type: str, status: str, duration_s: float) -> None:
    agent_invocations_total.labels(agent_type=agent_type, status=status).inc()
    agent_duration_seconds.labels(agent_type=agent_type).observe(duration_s)


def record_saga(status: str) -> None:
    saga_total.labels(status=status).inc()


def record_checkout_attempt(status: str) -> None:
    checkout_attempts_total.labels(status=status).inc()


def record_sourcing_result(vendor: str, status: str) -> None:
    sourcing_results_total.labels(vendor=vendor, status=status).inc()
