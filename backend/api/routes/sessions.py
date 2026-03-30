"""
Session creation endpoint (C-02).

Security guarantees:
  - user_id is ALWAYS generated server-side (UUID4). The client cannot
    supply or influence it — the request body has no user_id field.
  - The response returns a signed JWT (not the raw session_id), which
    the client must include as 'Authorization: Bearer <token>' on every
    protected request.
  - The raw session_id is included in the response for debugging/support
    use only; it cannot be used to authenticate without the JWT signature.
"""
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.middleware.rate_limit import limiter
from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.security import create_session_token
from backend.models.session import UserSession

router = APIRouter(prefix="/sessions", tags=["sessions"])
_settings = get_settings()


class CreateSessionRequest(BaseModel):
    """
    Intentionally empty — no client-supplied fields accepted.
    Clients may POST an empty body ({}) or omit the body entirely.
    """
    pass


class CreateSessionResponse(BaseModel):
    token: str        # Signed JWT — use as: Authorization: Bearer <token>
    session_id: str   # Opaque DB key (debugging / support only)
    user_id: str      # Server-generated UUID4
    expires_at: datetime


@router.post("", response_model=CreateSessionResponse, status_code=201)
@limiter.limit(f"{_settings.rate_limit_session_per_minute}/minute")
async def create_session(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: CreateSessionRequest | None = None,
) -> CreateSessionResponse:
    """
    Create a new user session.

    Always generates a fresh server-side user_id (UUID4).
    Never accepts user_id from the request body.
    Returns a signed JWT that the client must present as a Bearer token
    on all protected routes.
    """
    # user_id is unconditionally generated server-side — never from client input
    user_id = str(uuid.uuid4())

    session = UserSession(
        user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )

    from backend.repositories.session_repo import SessionRepository
    repo = SessionRepository(db)
    await repo.create(session)

    token = create_session_token(
        user_id=session.user_id,
        session_id=session.session_id,
    )

    return CreateSessionResponse(
        token=token,
        session_id=session.session_id,
        user_id=session.user_id,
        expires_at=session.expires_at,
    )
