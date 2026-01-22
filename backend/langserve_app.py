from __future__ import annotations

import base64
import os
import tempfile
from typing import Any, Dict, Optional

from fastapi import FastAPI
from langchain_core.runnables import RunnableLambda
from langserve import add_routes
from pydantic.v1 import BaseModel

from backend.agentic_graph.orchestrator import (
    run_saga_preview_sync,
    run_saga_sync,
)
from backend.agentic_graph.utils import state_to_payload
from backend.apps.coordinator.profile import DEFAULT_CHECKOUT_PROFILE
from backend.libs.schemas.models import PaymentInput


class PreviewInput(BaseModel):
    image_base64: str
    user_text: Optional[str] = None
    preferred_offer_url: Optional[str] = None


class StartInput(PreviewInput):
    payment: Dict[str, Any]
    idempotency_key: Optional[str] = None


def _save_temp_image(image_base64: str) -> str:
    data = base64.b64decode(image_base64)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(data)
        return tmp.name


def _preview_handler(payload: PreviewInput) -> dict:
    tmp_path = _save_temp_image(payload.image_base64)
    try:
        state = run_saga_preview_sync(
            image_path=tmp_path,
            user_text=payload.user_text,
            preferred_offer_url=payload.preferred_offer_url,
        )
        result = state_to_payload(state)
        result["profile"] = DEFAULT_CHECKOUT_PROFILE.model_copy()
        return result
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _start_handler(payload: StartInput) -> dict:
    tmp_path = _save_temp_image(payload.image_base64)
    try:
        payment = PaymentInput.model_validate(payload.payment)
        state = run_saga_sync(
            image_path=tmp_path,
            user_text=payload.user_text,
            payment=payment,
            preferred_offer_url=payload.preferred_offer_url,
            idempotency_key=payload.idempotency_key,
        )
        result = state_to_payload(state)
        result["profile"] = DEFAULT_CHECKOUT_PROFILE.model_copy()
        return result
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


preview_runnable = RunnableLambda(
    lambda inputs: _preview_handler(PreviewInput.model_validate(inputs))
)
start_runnable = RunnableLambda(
    lambda inputs: _start_handler(StartInput.model_validate(inputs))
)

app = FastAPI(title="Agentic Purchase - LangServe Host")

add_routes(
    app,
    preview_runnable,
    path="/saga/preview",
    input_type=PreviewInput,
)

add_routes(
    app,
    start_runnable,
    path="/saga/start",
    input_type=StartInput,
)
