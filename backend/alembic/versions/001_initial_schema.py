"""Initial schema: user_sessions, purchase_sagas, receipts

Revision ID: 001
Revises:
Create Date: 2026-02-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("session_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    op.create_table(
        "purchase_sagas",
        sa.Column("saga_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("user_sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.VARCHAR(32), nullable=False, default="created"),
        sa.Column("parsed_intent", JSONB, nullable=True),
        sa.Column("ranked_offers", JSONB, nullable=False, server_default="[]"),
        sa.Column("selected_offer", JSONB, nullable=True),
        sa.Column("receipt_id", UUID(as_uuid=True), nullable=True),
        sa.Column("error_reason", sa.TEXT, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_purchase_sagas_user_id", "purchase_sagas", ["user_id"])
    op.create_index("ix_purchase_sagas_session_id", "purchase_sagas", ["session_id"])
    op.create_index("ix_purchase_sagas_status", "purchase_sagas", ["status"])

    op.create_table(
        "receipts",
        sa.Column("receipt_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "saga_id",
            UUID(as_uuid=True),
            sa.ForeignKey("purchase_sagas.saga_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.VARCHAR(255), nullable=False, unique=True),
        sa.Column("offer_snapshot", JSONB, nullable=False),
        sa.Column("shipping_address", JSONB, nullable=False),
        sa.Column("amount", sa.NUMERIC(10, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_receipts_user_id", "receipts", ["user_id"])
    op.create_index("ix_receipts_saga_id", "receipts", ["saga_id"])


def downgrade() -> None:
    op.drop_table("receipts")
    op.drop_table("purchase_sagas")
    op.drop_table("user_sessions")
