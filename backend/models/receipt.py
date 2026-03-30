import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CHAR, NUMERIC, TIMESTAMP, VARCHAR, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base
from backend.models.common import Address
from backend.models.offer import RankedOffer
from pydantic import BaseModel, Field


# ── SQLAlchemy ORM ────────────────────────────────────────────────────────────

class ReceiptORM(Base):
    __tablename__ = "receipts"

    receipt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    saga_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stripe_payment_intent_id: Mapped[str] = mapped_column(VARCHAR(255), nullable=False, unique=True)
    offer_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    shipping_address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    amount: Mapped[Decimal] = mapped_column(NUMERIC(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


# ── Pydantic schema ───────────────────────────────────────────────────────────

class Receipt(BaseModel):
    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    saga_id: str
    user_id: str
    stripe_payment_intent_id: str
    offer_snapshot: RankedOffer
    shipping_address: Address
    amount: float
    currency: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
