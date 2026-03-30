import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.receipt import Receipt, ReceiptORM


class ReceiptRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, receipt: Receipt) -> Receipt:
        orm = ReceiptORM(
            receipt_id=uuid.UUID(receipt.receipt_id),
            saga_id=uuid.UUID(receipt.saga_id),
            user_id=uuid.UUID(receipt.user_id),
            stripe_payment_intent_id=receipt.stripe_payment_intent_id,
            offer_snapshot=receipt.offer_snapshot.model_dump(),
            shipping_address=receipt.shipping_address.model_dump(),
            amount=Decimal(str(receipt.amount)),
            currency=receipt.currency.upper(),
        )
        self._db.add(orm)
        await self._db.flush()
        return receipt

    async def get(self, receipt_id: str) -> Receipt | None:
        result = await self._db.execute(
            select(ReceiptORM).where(
                ReceiptORM.receipt_id == uuid.UUID(receipt_id)
            )
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return None
        return Receipt(
            receipt_id=str(orm.receipt_id),
            saga_id=str(orm.saga_id),
            user_id=str(orm.user_id),
            stripe_payment_intent_id=orm.stripe_payment_intent_id,
            offer_snapshot=orm.offer_snapshot,
            shipping_address=orm.shipping_address,
            amount=float(orm.amount),
            currency=orm.currency,
            created_at=orm.created_at,
        )
