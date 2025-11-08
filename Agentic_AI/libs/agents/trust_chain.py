from __future__ import annotations

import json
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from ..schemas.models import Offer, TrustAssessment
from .llm import get_chat_model


class TrustDecision(BaseModel):
    risk: str = Field(description="Risk level: low, medium, or high.")
    reasoning: str | None = Field(default=None, description="Short justification.")


_parser = PydanticOutputParser(pydantic_object=TrustDecision)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You evaluate vendor trustworthiness. Choose risk as low, medium, or high based on the data.",
        ),
        (
            "human",
            "Offer:\n{offer_json}\n\n"
            "Vendor telemetry:\n{profile_json}\n\n"
            "Baseline risk computed by heuristics: {baseline_risk}\n\n"
            "{format_instructions}",
        ),
    ]
)


async def llm_adjust_trust(
    offer: Offer,
    assessment: TrustAssessment,
    profile: dict[str, Any],
    *,
    config: RunnableConfig | dict[str, Any] | None = None,
) -> TrustAssessment:
    llm = get_chat_model(feature="trust")
    chain = _PROMPT | llm | _parser
    payload = {
        "offer_json": json.dumps(offer.model_dump(mode="json"), indent=2, ensure_ascii=False),
        "profile_json": json.dumps(profile, indent=2, ensure_ascii=False),
        "baseline_risk": assessment.risk,
        "format_instructions": _parser.get_format_instructions(),
    }
    decision = await chain.ainvoke(payload, config=config)
    risk_normalized = decision.risk.strip().lower()
    if risk_normalized not in {"low", "medium", "high"}:
        return assessment

    return assessment.model_copy(update={"risk": risk_normalized})
