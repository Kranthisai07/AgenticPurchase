"""
RankingAgent — produces a composite-scored ranked list of up to 5 offers.

Uses the weighted formula from formula.py.
Detects near-ties and surfaces a clarifying question when needed.
"""
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.agents.base import BaseAgent
from backend.agents.ranking.formula import detect_near_tie, rank_offers
from backend.core.config import get_settings
from backend.models.agent_messages import AgentType
from backend.models.agent_results import RankingSuccess
from backend.models.agent_tasks import RankingTask
from backend.models.offer import RankedOffer

_TIE_EXPLANATION_PROMPT = SystemMessage(
    content=(
        "You are a shopping assistant. Two product offers are nearly tied in score. "
        "Generate ONE short, specific question to help the user choose between them. "
        "Focus on the key differentiator (price vs. shipping, trust vs. rating, etc.)."
    )
)


class RankingAgent(BaseAgent):
    agent_type = AgentType.RANKING
    timeout = 10

    def __init__(self) -> None:
        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.openai_model_executor,
            api_key=settings.openai_api_key,
            temperature=0.3,
        )
        super().__init__(llm=llm)

    async def _execute(self, task: RankingTask) -> RankingSuccess:
        if not task.scored_offers:
            return RankingSuccess(
                ranked_offers=[],
                ranking_explanation="No offers available to rank.",
                near_tie_detected=False,
            )

        ranked = rank_offers(task.scored_offers, task.parsed_intent.primary_query)
        is_near_tie = detect_near_tie(ranked)

        near_tie_question: str | None = None
        if is_near_tie and len(ranked) >= 2:
            near_tie_question = await self._generate_tie_question(ranked[0], ranked[1])

        explanation = self._build_explanation(ranked[0], task.parsed_intent.primary_query) if ranked else ""

        return RankingSuccess(
            ranked_offers=ranked,
            ranking_explanation=explanation,
            near_tie_detected=is_near_tie,
            near_tie_question=near_tie_question,
        )

    def _build_explanation(self, top: RankedOffer, query: str) -> str:
        parts = []
        if top.trust_score.signals.rating is not None:
            parts.append(f"{top.trust_score.signals.rating:.1f}★ seller")
        if top.free_shipping:
            parts.append("free shipping")
        price_str = f"${top.price.amount:.2f}"
        return (
            f"Top pick: '{top.title}' at {price_str} from {top.seller_name}. "
            + (f"Highlights: {', '.join(parts)}." if parts else "")
        )

    async def _generate_tie_question(
        self, offer1: RankedOffer, offer2: RankedOffer
    ) -> str:
        user_msg = HumanMessage(
            content=(
                f"Option A: '{offer1.title}' — ${offer1.price.amount:.2f}, "
                f"trust score {offer1.trust_score.score:.0f}/100, "
                f"free shipping: {offer1.free_shipping}\n"
                f"Option B: '{offer2.title}' — ${offer2.price.amount:.2f}, "
                f"trust score {offer2.trust_score.score:.0f}/100, "
                f"free shipping: {offer2.free_shipping}\n"
                "What one question would help the user pick?"
            )
        )
        try:
            response = await self._invoke_llm([_TIE_EXPLANATION_PROMPT, user_msg])
            return response.content.strip()
        except Exception:
            return "Do you prefer the cheaper option or the one with a better seller reputation?"

    async def _self_evaluate(self, result: Any) -> tuple[bool, str]:
        if not isinstance(result, RankingSuccess):
            return False, "unexpected result type"
        for offer in result.ranked_offers:
            if offer.composite_score < 0 or offer.composite_score > 100:
                return False, f"composite_score {offer.composite_score} out of range"
        return True, ""
