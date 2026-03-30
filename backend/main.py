"""
FastAPI application factory + lifespan manager.
Registers all agents into the AgentBus on startup.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import stripe
import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.api.middleware.logging_middleware import LoggingMiddleware
from backend.api.middleware.rate_limit import limiter
from backend.api.middleware.request_id import RequestIDMiddleware
from backend.api.middleware.timing import TimingMiddleware
from backend.api.routes import checkout, health, saga, sessions, webhooks
from backend.agents.bus import get_agent_bus
from backend.agents.checkout.agent import CheckoutAgent
from backend.agents.intent.agent import IntentAgent
from backend.agents.ranking.agent import RankingAgent
from backend.agents.sourcing.agent import SourcingAgent
from backend.agents.trust.agent import TrustAgent
from backend.agents.vision.agent import VisionAgent
from backend.core.config import get_settings
from backend.core.database import close_engine
from backend.core.logging import setup_logging
from backend.core.redis import close_redis
from backend.core.telemetry import setup_telemetry

_INSECURE_APP_SECRET = "dev-secret-change-in-production"


def validate_required_config(settings) -> None:
    """
    Refuse to start if critical secrets are missing or set to insecure defaults.
    Called once during lifespan startup, before the app accepts any requests.
    """
    import sys

    errors = []

    if not settings.jwt_secret_key or settings.jwt_secret_key.strip() == "":
        errors.append(
            "JWT_SECRET_KEY is not set. "
            "Set a strong random secret (min 32 chars) in your environment."
        )

    if (
        not settings.app_secret_key
        or settings.app_secret_key == _INSECURE_APP_SECRET
    ):
        errors.append(
            "APP_SECRET_KEY is using the insecure default value. "
            "Set a strong random secret in your environment."
        )

    if not settings.openai_api_key or settings.openai_api_key.strip() == "":
        errors.append(
            "OPENAI_API_KEY is not set. "
            "Vision, Intent, and Trust agents will fail at runtime."
        )

    if not settings.stripe_secret_key or settings.stripe_secret_key.strip() == "":
        errors.append(
            "STRIPE_SECRET_KEY is not set. "
            "Checkout agent will fail at runtime."
        )

    if errors:
        print("\n[STARTUP ERROR] Missing or insecure configuration:")
        for e in errors:
            print(f"  - {e}")
        print("\nSet these values in your .env file before starting the server.")
        sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=settings.is_production)
    validate_required_config(settings)
    setup_telemetry()

    # Initialise Stripe SDK once at startup so every part of the app shares
    # the same API key without relying on per-instance StripeClient.__init__.
    if settings.stripe_secret_key:
        stripe.api_key = settings.stripe_secret_key

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            traces_sample_rate=0.1,
        )

    # Register all executor agents into the AgentBus
    bus = get_agent_bus()
    bus.register(VisionAgent())
    bus.register(IntentAgent())

    # Sourcing: one class registered once — handles ebay and serpapi via task.source.
    # Etsy removed — API key not available.
    bus.register(SourcingAgent())   # one instance handles all sources via task.source
    bus.register(TrustAgent())
    bus.register(RankingAgent())
    bus.register(CheckoutAgent())

    yield

    await close_engine()
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Agentic Purchase System",
        description="Multi-agent autonomous purchase system",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )

    # H-06: wire slowapi rate limiter.
    # The limiter singleton lives in backend/api/middleware/rate_limit.py and is
    # imported by route modules that apply @limiter.limit() decorators.
    # Attaching it to app.state lets slowapi resolve the limiter at request time.
    # Unrated routes (GET /health, GET /metrics, POST /webhooks/stripe,
    # GET /saga/{id}/stream) are intentionally left without a @limiter.limit()
    # decorator and are therefore never rate-limited.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Custom middleware (order matters: outermost first)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # Routers
    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(saga.router)
    app.include_router(checkout.router)
    app.include_router(webhooks.router)

    # Prometheus metrics endpoint — scraped by Prometheus; not rate-limited
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    return app


app = create_app()
