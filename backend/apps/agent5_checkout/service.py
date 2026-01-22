from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ...libs.schemas.models import Offer, PaymentInput, Receipt
from .main import pay as process_payment

app = FastAPI(title="Agent 5 - Checkout", version="0.1.0")


class PayRequest(BaseModel):
    offer: Offer
    payment: PaymentInput
    idempotency_key: str | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/pay", response_model=Receipt)
async def pay(payload: PayRequest) -> Receipt:
    try:
        return await process_payment(payload.offer, payload.payment, payload.idempotency_key or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"checkout_failed: {exc}") from exc


@app.get("/metrics")
async def metrics() -> dict[str, object]:
    try:
        from ..coordinator.metrics import TOKENS  # type: ignore
        stats = TOKENS.summary() if TOKENS else {}
    except Exception:
        stats = {}
    return {"tokens": stats}
