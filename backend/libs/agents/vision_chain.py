from __future__ import annotations

import json
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from ..schemas.models import ProductHypothesis
from .llm import get_chat_model


class VisionRefinement(BaseModel):
    label: str = Field(description="Primary class label for the product, lower case noun.")
    display_name: str | None = Field(
        default=None,
        description="User-friendly display name (keep short, e.g., 'stainless water bottle').",
    )
    brand: str | None = Field(default=None, description="Detected brand name if present.")
    color: str | None = Field(default=None, description="Dominant color (lower case).")
    category: str | None = Field(
        default=None,
        description="High-level category that downstream agents can use (e.g., drinkware, electronics).",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional confidence score between 0 and 1.",
    )
    reasoning: str | None = Field(
        default=None,
        description="Optional short justification for debugging.",
    )


_parser = PydanticOutputParser(pydantic_object=VisionRefinement)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are refining the output of a vision detector for a shopping assistant. "
            "Given the raw detector hypothesis and additional evidence, adjust fields conservatively. "
            "Only change values when the evidence strongly suggests a better choice. "
            "Use the detector label as a bias but fix obvious mistakes. "
            "Return JSON that matches the format instructions exactly.",
        ),
        (
            "human",
            "Detector hypothesis:\n{base_hypothesis}\n\n"
            "Supplemental evidence:\n{evidence}\n\n"
            "{format_instructions}",
        ),
    ]
)


async def refine_hypothesis_with_llm(
    base: ProductHypothesis,
    evidence: dict[str, Any] | None = None,
    *,
    config: RunnableConfig | dict[str, Any] | None = None,
) -> ProductHypothesis:
    llm = get_chat_model(feature="vision")
    chain = _PROMPT | llm | _parser
    payload = {
        "base_hypothesis": json.dumps(base.model_dump(mode="json"), indent=2, ensure_ascii=False),
        "evidence": json.dumps(evidence or {}, indent=2, ensure_ascii=False),
        "format_instructions": _parser.get_format_instructions(),
    }
    refined = await chain.ainvoke(payload, config=config)

    updates: dict[str, Any] = {}
    if refined.label:
        updates["label"] = refined.label.strip()
    if refined.display_name is not None:
        updates["display_name"] = refined.display_name.strip() or None
    if refined.brand is not None:
        updates["brand"] = refined.brand.strip() or None
    if refined.color is not None:
        updates["color"] = refined.color.strip() or None
    if refined.category is not None:
        updates["category"] = refined.category.strip() or None
        updates["item_type"] = refined.category.strip() or None
    if refined.confidence is not None:
        updates["confidence"] = float(refined.confidence)

    return base.model_copy(update=updates)
