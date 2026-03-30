from __future__ import annotations

import os
import json
from typing import Any, List

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from ..schemas.models import Offer, PurchaseIntent
from .llm import get_chat_model


class OfferRanking(BaseModel):
    """LLM response describing the preferred ordering of offers."""

    ranked_indices: List[int] = Field(
        description="List of offer indices in descending preference (0-based)."
    )
    reasoning: str | None = Field(
        default=None,
        description="Optional explanation of the ranking.",
    )


_parser = PydanticOutputParser(pydantic_object=OfferRanking)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You help rank vendor offers for a shopper's intent. "
            "Review the candidates and return the indices sorted from best to worst. "
            "Only include indices that exist. Favor offers that match the requested item, brand, color, "
            "stay under budget when specified, and ship quickly at a fair price.",
        ),
        (
            "human",
            "Purchase intent:\n{intent_json}\n\n"
            "Candidate offers (JSON list with index field):\n{offers_json}\n\n"
            "{format_instructions}",
        ),
    ]
)


async def rerank_offers_with_llm(
    intent: PurchaseIntent,
    offers: list[Offer],
    *,
    config: RunnableConfig | dict[str, Any] | None = None,
    budgeter=None,
    state: str = "S3",
) -> list[Offer]:
    """
    Reorder offers using an LLM ranking chain. Returns the reordered list.
    If a token budgeter is provided, apply budget enforcement and token accounting.
    """
    if len(offers) <= 1:
        return offers

    llm = get_chat_model(feature="sourcing")
    chain = _PROMPT | llm | _parser

    enriched = [
        {
            "index": idx,
            "vendor": offer.vendor,
            "title": offer.title,
            "price_usd": offer.price_usd,
            "shipping_days": offer.shipping_days,
            "eta_days": offer.eta_days,
            "category": offer.category,
            "color_keywords": offer.keywords,
        }
        for idx, offer in enumerate(offers)
    ]
    payload = {
        "intent_json": json.dumps(intent.model_dump(mode="json"), indent=2, ensure_ascii=False),
        "offers_json": json.dumps(enriched, indent=2, ensure_ascii=False),
        "format_instructions": _parser.get_format_instructions(),
    }

    result = None
    model_name = getattr(llm, "model", None) or getattr(llm, "model_name", None) or (os.getenv("LANGCHAIN_MODEL") or "gpt-4o-mini")

    if budgeter is not None:
        try:
            from apps.coordinator.metrics_tokens import count_tokens
            prompt_text = json.dumps(payload, ensure_ascii=False)
            prompt_tokens = count_tokens(model_name, prompt_text)
            act = budgeter.enforce_before_call(state, prompt_tokens)
            if act == "block":
                raise RuntimeError("token_budget_block: S3")
            if act == "fallback":
                budgeter.charge(state, "llm", model_name, "prompt", 0)
                return offers
            # configure truncation by binding max_tokens when supported
            run_chain = chain
            if act == "truncate":
                remaining = budgeter.remaining(state)
                max_out = max(0, remaining - prompt_tokens - 32)
                try:
                    run_chain = _PROMPT | llm.bind(max_tokens=max_out) | _parser
                except Exception:
                    run_chain = chain
            budgeter.charge(state, "llm", model_name, "prompt", prompt_tokens)
            result = await run_chain.ainvoke(payload, config=config)
            # estimate completion tokens and charge
            try:
                comp_obj = result.model_dump()  # type: ignore[attr-defined]
            except Exception:
                try:
                    comp_obj = result.__dict__
                except Exception:
                    comp_obj = str(result)
            comp_json = json.dumps(comp_obj, ensure_ascii=False)
            completion_tokens = count_tokens(model_name, comp_json)
            budgeter.charge(state, "llm", model_name, "completion", completion_tokens)
        except Exception:
            # fall back to plain call if budgeting fails
            result = await chain.ainvoke(payload, config=config)
    else:
        result = await chain.ainvoke(payload, config=config)

    order: list[int] = []
    seen: set[int] = set()
    for idx in result.ranked_indices:
        if 0 <= idx < len(offers) and idx not in seen:
            order.append(idx)
            seen.add(idx)
    for idx in range(len(offers)):
        if idx not in seen:
            order.append(idx)

    return [offers[i] for i in order]
