"""
Checkout route — not used directly (checkout is triggered via saga/resume).
Kept for direct checkout status queries.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.dependencies import SessionContext, get_current_session

router = APIRouter(prefix="/checkout", tags=["checkout"])


class CheckoutStatusResponse(BaseModel):
    saga_id: str
    receipt_id: str | None
    status: str


@router.get("/{saga_id}/status", response_model=CheckoutStatusResponse)
async def get_checkout_status(
    saga_id: str,
    session: Annotated[SessionContext, Depends(get_current_session)],
) -> CheckoutStatusResponse:
    """Get the checkout status for a saga. Requires a valid Bearer JWT."""
    from backend.core.redis import get_saga_state
    state = await get_saga_state(saga_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Saga '{saga_id}' not found")

    # Verify this saga belongs to the authenticated user
    if state.get("user_id") != session.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return CheckoutStatusResponse(
        saga_id=saga_id,
        receipt_id=state.get("receipt_id"),
        status=state.get("saga_status", "unknown"),
    )
