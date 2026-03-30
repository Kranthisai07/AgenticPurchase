import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import TIMESTAMP, TEXT, VARCHAR, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base
from pydantic import BaseModel, Field


# ── SQLAlchemy ORM ────────────────────────────────────────────────────────────

class WebhookEventORM(Base):
    __tablename__ = "stripe_webhook_events"

    stripe_event_id: Mapped[str] = mapped_column(VARCHAR(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    saga_id: Mapped[str | None] = mapped_column(VARCHAR(36), nullable=True)
    status: Mapped[str] = mapped_column(VARCHAR(32), nullable=False, default="processing")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


# ── Pydantic schema ───────────────────────────────────────────────────────────

class WebhookEvent(BaseModel):
    stripe_event_id: str
    event_type: str
    saga_id: str | None = None
    status: Literal["processing", "completed", "failed"] = "processing"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: datetime | None = None
