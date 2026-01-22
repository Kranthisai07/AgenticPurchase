from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ..schemas.models import ProductHypothesis, PurchaseIntent
from .llm import get_chat_model

_parser = PydanticOutputParser(pydantic_object=PurchaseIntent)

_SYSTEM_TMPL = (
    "You are a shopping assistant converting observations from a vision system and a user's request "
    "into a well-structured purchase intent for downstream agents. "
    "Return JSON that exactly matches the schema in the format instructions. "
    "Infer reasonable defaults when the user omits fields, but never hallucinate impossible values. "
    "Quantities must be positive integers. If the user does not state quantity, default to 1. "
    "Budget should be omitted when not mentioned. Keep color/brand empty when unknown. "
    "Ensure the response is valid JSON with double quotes."
)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM_TMPL + "\n\n{format_instructions}"),
        (
            "human",
            "Vision hypothesis:\n{hypothesis_json}\n\n"
            "User request: {user_request}\n\n"
            "If the user request is empty, rely on the hypothesis and set defaults conservatively.",
        ),
    ]
)


def _ensure_llm(model: str | None = None) -> BaseChatModel:
    return get_chat_model(feature="intent", explicit_model=model)


async def run_intent_chain(
    hypothesis: ProductHypothesis,
    user_request: str | None,
    *,
    model: str | None = None,
    config: RunnableConfig | dict[str, Any] | None = None,
) -> PurchaseIntent:
    """
    Generate a PurchaseIntent using an LLM via LangChain.

    Args:
        hypothesis: ProductHypothesis coming from the vision agent.
        user_request: Free-form text from the user (can be empty/None).
        model: Optional override for the LLM model name.
        config: Optional RunnableConfig overrides passed to the chain (e.g., callbacks, tags).
    """
    llm = _ensure_llm(model)
    chain = _PROMPT | llm | _parser
    payload = {
        "hypothesis_json": json.dumps(
            hypothesis.model_dump(mode="json"), indent=2, ensure_ascii=False
        ),
        "user_request": (user_request or "").strip(),
        "format_instructions": _parser.get_format_instructions(),
    }
    return await chain.ainvoke(payload, config=config)
