from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.webhook import WebhookEvent, WebhookEventORM


class WebhookRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def exists(self, stripe_event_id: str) -> bool:
        """Return True if this Stripe event ID was already recorded."""
        result = await self._db.execute(
            select(WebhookEventORM.stripe_event_id).where(
                WebhookEventORM.stripe_event_id == stripe_event_id
            )
        )
        return result.scalar_one_or_none() is not None

    async def create(self, event: WebhookEvent) -> None:
        """Insert a new webhook event record with status 'processing'."""
        orm = WebhookEventORM(
            stripe_event_id=event.stripe_event_id,
            event_type=event.event_type,
            saga_id=event.saga_id,
            status=event.status,
            created_at=event.created_at,
            processed_at=event.processed_at,
        )
        self._db.add(orm)
        await self._db.flush()

    async def update_status(
        self, stripe_event_id: str, status: str
    ) -> None:
        """Update the status of a webhook event, setting processed_at on terminal states."""
        result = await self._db.execute(
            select(WebhookEventORM).where(
                WebhookEventORM.stripe_event_id == stripe_event_id
            )
        )
        orm = result.scalar_one_or_none()
        if orm:
            orm.status = status
            if status in ("completed", "failed"):
                orm.processed_at = datetime.utcnow()
