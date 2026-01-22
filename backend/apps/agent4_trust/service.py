from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from ...libs.schemas.models import Offer, TrustAssessment
from .main import assess as assess_offer

app = FastAPI(title="Agent 4 - Trust", version="0.1.0")


class AssessRequest(BaseModel):
    offer: Offer


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/assess", response_model=TrustAssessment)
async def assess(payload: AssessRequest) -> TrustAssessment:
    return await assess_offer(payload.offer)


@app.get("/metrics")
async def metrics() -> dict[str, object]:
    try:
        from ..coordinator.metrics import TOKENS  # type: ignore
        stats = TOKENS.summary() if TOKENS else {}
    except Exception:
        stats = {}
    return {"tokens": stats}
