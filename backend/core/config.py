from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    app_secret_key: str = "dev-secret-change-in-production"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agentic_purchase"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_saga_ttl_seconds: int = 1800

    # OpenAI
    openai_api_key: str = ""
    openai_model_orchestrator: str = "gpt-4o"
    openai_model_executor: str = "gpt-4o-mini"

    # Stripe
    stripe_secret_key: str = ""           # sk_live_... or sk_test_...
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""       # whsec_... from Stripe dashboard — separate from stripe_secret_key
    stripe_currency: str = "usd"

    # JWT session tokens (C-02)
    jwt_secret_key: str = ""              # long random string; generate with: openssl rand -hex 32
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # Rate limiting (H-06)
    # Controls POST /saga and POST /sessions throughput.
    # Set rate_limit_enabled=false to disable limiting (e.g. in integration tests).
    rate_limit_saga_per_minute: int = 5
    rate_limit_session_per_minute: int = 10
    rate_limit_enabled: bool = True

    # Etsy removed — API key not available

    # eBay
    ebay_app_id: str = ""
    ebay_cert_id: str = ""
    ebay_dev_id: str = ""
    ebay_base_url: str = "https://api.ebay.com"

    # SerpApi
    serpapi_key: str = ""
    serpapi_base_url: str = "https://serpapi.com"

    # Supermemory
    supermemory_api_key: str = ""
    supermemory_base_url: str = "https://api.supermemory.ai"

    # Sentry
    sentry_dsn: str = ""

    # Checkout velocity
    checkout_max_attempts_per_hour: int = 3

    # Sourcing timeouts (H-03)
    # sourcing_agent_timeout: per-agent seconds — each vendor gets this individually
    #   (enforced by SourcingAgent.timeout; this value is passed for documentation)
    # sourcing_aggregate_timeout: wall-clock budget for ALL vendors combined;
    #   must be > sourcing_agent_timeout so the fastest agent can return even if
    #   the slowest times out
    sourcing_agent_timeout: int = 20
    sourcing_aggregate_timeout: int = 25

    # Trust timeouts (H-03)
    trust_agent_timeout: int = 15
    trust_aggregate_timeout: int = 20

    # Total saga ceiling (H-03)
    # 2 minutes — if the saga as a whole exceeds this, fail gracefully
    saga_total_timeout: int = 120

    # Input hardening (H-05)
    # max_user_input_length: characters — inputs longer than this are rejected
    #   at the API layer before reaching any agent (POST /saga and POST /saga/resume).
    # injection_confidence_threshold: InjectionGuard confidence score at or above
    #   which user input is hard-blocked.  Below the threshold the guard logs a
    #   warning and allows the request to proceed (avoids false positives on
    #   legitimate edge-case queries).
    max_user_input_length: int = 2000
    injection_confidence_threshold: float = 0.7

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str) -> str:
        return v

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
