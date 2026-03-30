import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import TIMESTAMP, TEXT, VARCHAR, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base
from backend.models.intent import ParsedIntent
from backend.models.offer import RankedOffer
from pydantic import BaseModel, Field


class SagaStatus(str, Enum):
    CREATED = "created"
    VISION = "vision"
    INTENT = "intent"
    SOURCING = "sourcing"
    TRUST = "trust"
    RANKING = "ranking"
    AWAITING_USER = "awaiting_user"
    CHECKOUT = "checkout"
    COMPLETE = "complete"
    FAILED = "failed"


# ── SQLAlchemy ORM ────────────────────────────────────────────────────────────

class PurchaseSagaORM(Base):
    __tablename__ = "purchase_sagas"

    saga_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(32), nullable=False, default="created")
    parsed_intent: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ranked_offers: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    selected_offer: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Pydantic schema ───────────────────────────────────────────────────────────

class PurchaseSaga(BaseModel):
    saga_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    user_id: str
    status: SagaStatus = SagaStatus.CREATED
    parsed_intent: ParsedIntent | None = None
    ranked_offers: list[RankedOffer] = []
    selected_offer: RankedOffer | None = None
    receipt_id: str | None = None
    error_reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
