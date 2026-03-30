"""Add stripe_webhook_events table for idempotent webhook processing

Revision ID: 002
Revises: 001
Create Date: 2026-02-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stripe_webhook_events",
        sa.Column("stripe_event_id", sa.VARCHAR(255), primary_key=True, nullable=False),
        sa.Column("event_type", sa.VARCHAR(128), nullable=False),
        sa.Column("saga_id", sa.VARCHAR(36), nullable=True),
        sa.Column("status", sa.VARCHAR(32), nullable=False, server_default="processing"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_stripe_webhook_events_saga_id",
        "stripe_webhook_events",
        ["saga_id"],
    )
    op.create_index(
        "ix_stripe_webhook_events_status",
        "stripe_webhook_events",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_stripe_webhook_events_status", table_name="stripe_webhook_events")
    op.drop_index("ix_stripe_webhook_events_saga_id", table_name="stripe_webhook_events")
    op.drop_table("stripe_webhook_events")
