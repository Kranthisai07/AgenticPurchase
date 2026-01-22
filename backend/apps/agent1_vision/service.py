from __future__ import annotations

import os
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile

from ...libs.schemas.models import ProductHypothesis
from .main import intake_image

app = FastAPI(title="Agent 1 - Vision", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/intake", response_model=ProductHypothesis)
async def intake(image: UploadFile = File(...)) -> ProductHypothesis:
    suffix = os.path.splitext(image.filename or "")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        contents = await image.read()
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        return await intake_image(tmp_path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"vision_failed: {exc}") from exc
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@app.get("/metrics")
async def metrics() -> dict[str, object]:
    """
    Expose basic token counters for aggregation by the coordinator.
    When running in-process this is optional, but for the multi-service
    deployment we reuse the coordinator's metrics module to provide a
    compatible structure.
    """
    try:
        from apps.coordinator.metrics import TOKENS  # type: ignore
        stats = TOKENS.summary() if TOKENS else {}
    except Exception:
        stats = {}
    return {"tokens": stats}
