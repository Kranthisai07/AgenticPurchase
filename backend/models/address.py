"""
Persisted shipping-address model (C-03).

This is distinct from backend.models.common.Address, which is an
in-memory value object used in CheckoutTask and Receipt.

This model owns a Postgres row with a server-generated UUID so that:
  1. The full address is stored once in Postgres (encrypted at rest).
  2. LangGraph state / Redis only ever sees the address_id UUID string.
  3. PII never passes through the checkpoint store unencrypted.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import TIMESTAMP, VARCHAR, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


# ── SQLAlchemy ORM ────────────────────────────────────────────────────────────

class AddressORM(Base):
    __tablename__ = "addresses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    line1: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    line2: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    city: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    state: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    postal_code: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    country: Mapped[str] = mapped_column(VARCHAR(2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


# ── Pydantic schema ───────────────────────────────────────────────────────────

class Address(BaseModel):
    """
    Persisted shipping address.  id is server-generated — never supplied by
    the client.  Only address_id (str) is stored in OrchestratorState/Redis.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    line1: str
    line2: str | None = None
    city: str
    state: str
    postal_code: str
    country: str                    # ISO 3166-1 alpha-2
    created_at: datetime = Field(default_factory=datetime.utcnow)
