import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.address import Address, AddressORM


class AddressRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, address: Address) -> str:
        """Insert address to Postgres. Returns address_id (UUID string)."""
        orm = AddressORM(
            id=uuid.UUID(address.id),
            user_id=uuid.UUID(address.user_id),
            line1=address.line1,
            line2=address.line2,
            city=address.city,
            state=address.state,
            postal_code=address.postal_code,
            country=address.country,
            created_at=address.created_at,
        )
        self._db.add(orm)
        await self._db.flush()
        return address.id

    async def get(self, address_id: str) -> Address:
        """Fetch address by ID. Raises ValueError if not found."""
        result = await self._db.execute(
            select(AddressORM).where(AddressORM.id == uuid.UUID(address_id))
        )
        orm = result.scalar_one_or_none()
        if not orm:
            raise ValueError(f"Address '{address_id}' not found")
        return Address(
            id=str(orm.id),
            user_id=str(orm.user_id),
            line1=orm.line1,
            line2=orm.line2,
            city=orm.city,
            state=orm.state,
            postal_code=orm.postal_code,
            country=orm.country,
            created_at=orm.created_at,
        )
