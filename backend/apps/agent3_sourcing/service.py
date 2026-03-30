from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from ...libs.schemas.models import Offer, PurchaseIntent
from .main import offers_for_intent

app = FastAPI(title="Agent 3 - Sourcing", version="0.1.0")


class OffersRequest(BaseModel):
    intent: PurchaseIntent
    top_k: int | None = 5


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/offers", response_model=list[Offer])
async def offers(payload: OffersRequest) -> list[Offer]:
    top_k = payload.top_k or 5
    return await offers_for_intent(payload.intent, top_k=top_k)


@app.get("/metrics")
async def metrics() -> dict[str, object]:
    try:
        from ..coordinator.metrics import TOKENS  # type: ignore
        stats = TOKENS.summary() if TOKENS else {}
    except Exception:
        stats = {}
    return {"tokens": stats}
