"""
IntentAgent — parses user input into structured search parameters.

Capabilities:
- Extracts ParsedIntent from product description + user text
- Detects and blocks prompt injection via two-stage LLM-based classifier (H-05)
- Requests clarification when intent is ambiguous (max 2 questions)
- Self-evaluates: checks for internal consistency before returning

Injection policy (H-05):
  InjectionGuard runs a two-stage check (static pre-filter + LLM classifier).
  - confidence >= INJECTION_CONFIDENCE_THRESHOLD → block, return IntentInjectionDetected
  - confidence < threshold → log warning, proceed with original input
    (avoids blocking legitimate edge-case queries)
"""
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.agents.base import BaseAgent
from backend.agents.intent.prompts import INTENT_SYSTEM_PROMPT, INTENT_USER_PROMPT
from backend.core.config import get_settings
from backend.core.injection_guard import InjectionGuard
from backend.models.agent_messages import AgentType
from backend.models.agent_results import (
    IntentClarification,
    IntentInjectionDetected,
    IntentSuccess,
)
from backend.models.agent_tasks import IntentTask
from backend.models.intent import ParsedIntent


class IntentAgent(BaseAgent):
    agent_type = AgentType.INTENT
    timeout = 10

    def __init__(
        self,
        injection_guard: InjectionGuard | None = None,
    ) -> None:
        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.openai_model_orchestrator,
            api_key=settings.openai_api_key,
            temperature=0,
        )
        super().__init__(llm=llm)
        # InjectionGuard can be injected for testing; defaults to sharing the agent LLM
        self._injection_guard = injection_guard or InjectionGuard(llm=llm)

    async def _execute(
        self, task: IntentTask
    ) -> IntentSuccess | IntentClarification | IntentInjectionDetected:
        settings = get_settings()
        combined_text = f"{task.product_description} {task.user_text or ''}".strip()

        # H-05: two-stage injection check (static pre-filter + LLM classifier)
        injection_result = await self._injection_guard.check(
            combined_text, context="user_input"
        )

        if injection_result.is_injection:
            if injection_result.confidence >= settings.injection_confidence_threshold:
                # High confidence — block entirely
                self._logger.warning(
                    "intent.injection_blocked",
                    confidence=injection_result.confidence,
                    reason=injection_result.reason,
                    stage=injection_result.stage,
                )
                return IntentInjectionDetected(
                    sanitized=False,
                    original_flagged=True,
                    proceeds_with=(
                        "I can only help with product searches. "
                        "Please describe what you're looking for."
                    ),
                )
            else:
                # Low confidence — log and proceed with original input
                self._logger.warning(
                    "intent.injection_suspected",
                    confidence=injection_result.confidence,
                    reason=injection_result.reason,
                    stage=injection_result.stage,
                )

        return await self._call_llm(task)

    async def _call_llm(
        self, task: IntentTask
    ) -> IntentSuccess | IntentClarification:
        history_str = "\n".join(
            f"{m.role}: {m.content}"
            for m in task.conversation_history[-3:]
        )
        prefs_str = task.user_preferences.model_dump_json()

        user_prompt = INTENT_USER_PROMPT.format(
            product_description=task.product_description,
            user_text=task.user_text or "(none)",
            user_preferences=prefs_str,
            conversation_history=history_str or "(none)",
        )

        messages = [
            SystemMessage(content=INTENT_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        response = await self._invoke_llm(messages)
        return self._parse_response(response.content)

    def _parse_response(self, content: str) -> IntentSuccess | IntentClarification:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        data = json.loads(cleaned)

        if data.get("needs_clarification") and data.get("clarification_questions"):
            partial = self._build_partial_intent(data)
            return IntentClarification(
                questions=data["clarification_questions"][:2],
                partial_intent=partial,
            )

        intent = ParsedIntent(
            primary_query=data.get("primary_query", ""),
            category=data.get("category", "general"),
            price_min=data.get("price_min"),
            price_max=data.get("price_max"),
            preferred_vendors=data.get("preferred_vendors", []),
            excluded_vendors=data.get("excluded_vendors", []),
            condition=data.get("condition", "any"),
            urgency=data.get("urgency", "any"),
            gift_wrapping=data.get("gift_wrapping", False),
            quantity=data.get("quantity", 1),
        )
        return IntentSuccess(parsed_intent=intent)

    def _build_partial_intent(self, data: dict) -> ParsedIntent:
        return ParsedIntent(
            primary_query=data.get("primary_query", ""),
            category=data.get("category", "general"),
            price_min=data.get("price_min"),
            price_max=data.get("price_max"),
            condition=data.get("condition", "any"),
            urgency=data.get("urgency", "any"),
        )

    async def _self_evaluate(self, result: Any) -> tuple[bool, str]:
        if isinstance(result, (IntentClarification, IntentInjectionDetected)):
            return True, ""

        if isinstance(result, IntentSuccess):
            intent = result.parsed_intent
            if not intent.primary_query.strip():
                return False, "primary_query is empty"
            if intent.price_min and intent.price_max:
                if intent.price_min > intent.price_max:
                    return False, f"price_min ({intent.price_min}) > price_max ({intent.price_max})"

        return True, ""
