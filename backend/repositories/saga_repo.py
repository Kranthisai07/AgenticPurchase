import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.saga import PurchaseSaga, PurchaseSagaORM, SagaStatus


class SagaRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, saga: PurchaseSaga) -> PurchaseSaga:
        orm = PurchaseSagaORM(
            saga_id=uuid.UUID(saga.saga_id),
            session_id=uuid.UUID(saga.session_id),
            user_id=uuid.UUID(saga.user_id),
            status=saga.status.value,
            parsed_intent=saga.parsed_intent.model_dump() if saga.parsed_intent else None,
            ranked_offers=[o.model_dump() for o in saga.ranked_offers],
            selected_offer=saga.selected_offer.model_dump() if saga.selected_offer else None,
        )
        self._db.add(orm)
        await self._db.flush()
        return saga

    async def get(self, saga_id: str) -> PurchaseSaga | None:
        result = await self._db.execute(
            select(PurchaseSagaORM).where(
                PurchaseSagaORM.saga_id == uuid.UUID(saga_id)
            )
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return None
        return self._to_pydantic(orm)

    async def update_status(self, saga_id: str, status: SagaStatus) -> None:
        result = await self._db.execute(
            select(PurchaseSagaORM).where(
                PurchaseSagaORM.saga_id == uuid.UUID(saga_id)
            )
        )
        orm = result.scalar_one_or_none()
        if orm:
            orm.status = status.value
            orm.updated_at = datetime.utcnow()

    async def update_status_raw(self, saga_id: str, status: str) -> None:
        """Update saga status using a raw string value (e.g. webhook-specific states)."""
        result = await self._db.execute(
            select(PurchaseSagaORM).where(
                PurchaseSagaORM.saga_id == uuid.UUID(saga_id)
            )
        )
        orm = result.scalar_one_or_none()
        if orm:
            orm.status = status
            orm.updated_at = datetime.utcnow()

    def _to_pydantic(self, orm: PurchaseSagaORM) -> PurchaseSaga:
        return PurchaseSaga(
            saga_id=str(orm.saga_id),
            session_id=str(orm.session_id),
            user_id=str(orm.user_id),
            status=SagaStatus(orm.status),
            error_reason=orm.error_reason,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )
