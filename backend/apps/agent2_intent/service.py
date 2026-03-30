from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ...libs.schemas.models import ProductHypothesis, PurchaseIntent
from .main import confirm_from_choice, confirm_intent, CHOICES
from ...libs.agents.intent_chain import run_intent_chain

app = FastAPI(title="Agent 2 - Intent", version="0.1.0")

logger = logging.getLogger(__name__)


class ConfirmRequest(BaseModel):
    hypothesis: ProductHypothesis
    user_text: str | None = None
    choice_key: str | None = None
    color_hint: str | None = None
    quantity: int | None = None
    budget_usd: float | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/confirm", response_model=PurchaseIntent)
async def confirm(payload: ConfirmRequest) -> PurchaseIntent:
    hypo = payload.hypothesis

    if payload.choice_key:
        choice = payload.choice_key
        if choice not in CHOICES.values():
            raise HTTPException(status_code=400, detail="unknown_choice_key")
        return confirm_from_choice(
            hypo,
            choice,
            color_hint=payload.color_hint,
            qty=payload.quantity,
            budget=payload.budget_usd,
        )

    if _langchain_enabled():
        try:
            return await run_intent_chain(
                hypo,
                payload.user_text,
            )
        except Exception as exc:
            logger.warning(
                "LangChain intent fallback triggered: %s", exc, exc_info=True
            )

    return await confirm_intent(hypo, user_text=payload.user_text)


def _langchain_enabled() -> bool:
    flag = os.getenv("USE_LANGCHAIN_INTENT", os.getenv("USE_LANGCHAIN", "0"))
    return flag is not None and flag.strip().lower() in {"1", "true", "yes"}


@app.get("/metrics")
async def metrics() -> dict[str, object]:
    try:
        from ..coordinator.metrics import TOKENS  # type: ignore
        stats = TOKENS.summary() if TOKENS else {}
    except Exception:
        stats = {}
    return {"tokens": stats}
