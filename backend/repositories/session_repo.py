import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session import UserSession, UserSessionORM


class SessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, session: UserSession) -> UserSession:
        orm = UserSessionORM(
            session_id=uuid.UUID(session.session_id),
            user_id=uuid.UUID(session.user_id),
            expires_at=session.expires_at,
            metadata_=session.metadata,
        )
        self._db.add(orm)
        await self._db.flush()
        return session

    async def get(self, session_id: str) -> UserSession | None:
        result = await self._db.execute(
            select(UserSessionORM).where(
                UserSessionORM.session_id == uuid.UUID(session_id),
                UserSessionORM.expires_at > datetime.utcnow(),
            )
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return None
        return UserSession(
            session_id=str(orm.session_id),
            user_id=str(orm.user_id),
            created_at=orm.created_at,
            expires_at=orm.expires_at,
            metadata=orm.metadata_,
        )
