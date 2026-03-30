"""
Reusable FastAPI dependency guards (C-02).

Usage on protected routes:

    from typing import Annotated
    from fastapi import Depends
    from backend.api.dependencies import get_current_session, SessionContext

    @router.post("/saga")
    async def start_saga(
        session: Annotated[SessionContext, Depends(get_current_session)],
        ...
    ) -> ...:
        # session.user_id  — verified from JWT sub claim
        # session.session_id — verified from JWT jti claim

Protected routes (require Bearer JWT):
  POST /saga
  GET  /saga/{saga_id}
  POST /saga/{saga_id}/resume
  GET  /saga/{saga_id}/pending-events

Public routes (no auth):
  POST /sessions          — creates the token
  POST /webhooks/stripe   — authenticated by Stripe HMAC signature
  GET  /health
"""
from dataclasses import dataclass

from fastapi import Header, HTTPException
from langchain_openai import ChatOpenAI

from backend.core.config import get_settings
from backend.core.injection_guard import InjectionGuard
from backend.core.security import verify_session_token


@dataclass
class SessionContext:
    """Verified identity extracted from a valid Bearer JWT."""
    user_id: str
    session_id: str


async def get_current_session(
    authorization: str | None = Header(None),
) -> SessionContext:
    """
    FastAPI dependency that validates the Authorization: Bearer <jwt> header.

    Returns a SessionContext with the verified user_id and session_id.
    Raises HTTP 401 on missing, expired, or invalid tokens.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ")

    try:
        claims = verify_session_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    return SessionContext(
        user_id=claims["sub"],
        session_id=claims["jti"],
    )


def get_injection_guard() -> InjectionGuard:
    """
    FastAPI dependency that returns a shared InjectionGuard instance.

    Uses the executor model (gpt-4o-mini) — cheaper than the orchestrator
    model and sufficient for binary classification tasks.
    """
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model_executor,
        api_key=settings.openai_api_key,
        temperature=0,
    )
    return InjectionGuard(llm=llm)
