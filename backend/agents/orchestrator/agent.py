"""
OrchestratorAgent — the only agent that talks to the user.
Drives the LangGraph state machine. Reads conversation history.
Makes all routing decisions based on executor agent results.
"""
import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog

from backend.agents.bus import AgentBus, get_agent_bus
from backend.agents.orchestrator.graph import compile_graph
from backend.core.config import get_settings
from backend.core.redis import get_saga_state, set_saga_state
from backend.models.intent import Message, UserPreferences
from backend.models.sse_events import SSEEvent, SSEEventType, SessionReadyPayload

logger = structlog.get_logger(__name__)

# Compiled graph is a module-level singleton (thread-safe, stateless structure)
_compiled_graph = None


def get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = compile_graph()
    return _compiled_graph


class OrchestratorAgent:
    """
    Central coordinator. Drives the purchase saga from start to finish.
    Emits SSE events for every state transition.
    """

    def __init__(self, bus: AgentBus | None = None) -> None:
        self._bus = bus or get_agent_bus()
        self._graph = get_compiled_graph()
        self._settings = get_settings()

    async def start_saga(
        self,
        *,
        saga_id: str,
        session_id: str,
        user_id: str,
        user_text: str | None,
        image_bytes: bytes | None,
        conversation_history: list[Message],
        user_preferences: UserPreferences | None,
        sse_emitter: Any,
    ) -> dict[str, Any]:
        """
        Start a new purchase saga. Runs the LangGraph graph asynchronously.
        SSE events are emitted via sse_emitter as each agent completes.
        """
        await sse_emitter(SSEEvent(
            event=SSEEventType.SESSION_READY,
            data=SessionReadyPayload(session_id=session_id, saga_id=saga_id),
        ))

        initial_state = {
            "saga_id": saga_id,
            "session_id": session_id,
            "user_id": user_id,
            "user_text": user_text,
            "image_bytes": image_bytes,
            "conversation_history": conversation_history,
            "user_preferences": user_preferences or UserPreferences(),
            "sse_emitter": sse_emitter,
            "retry_sourcing": False,
            "retry_checkout": False,
            "needs_clarification": False,
            "state_version": "1.0",
        }

        # Persist initial state to Redis
        await set_saga_state(saga_id, {k: v for k, v in initial_state.items() if k != "sse_emitter" and k != "image_bytes"})

        logger.info("orchestrator.saga_started", saga_id=saga_id, user_id=user_id)

        try:
            final_state = await self._graph.ainvoke(initial_state)
            await set_saga_state(saga_id, {k: v for k, v in final_state.items() if k != "sse_emitter" and k != "image_bytes"})
            return final_state
        except Exception as exc:
            logger.exception("orchestrator.saga_error", saga_id=saga_id, error=str(exc))
            raise

    async def resume_saga(
        self,
        *,
        saga_id: str,
        user_response: str,
        resume_at: str,
        sse_emitter: Any,
        selected_offer_index: int | None = None,
        stripe_payment_method_id: str | None = None,
        shipping_address: Any | None = None,
    ) -> dict[str, Any]:
        """
        Resume a paused saga after user input (clarification, tie-breaking, offer selection).
        """
        cached = await get_saga_state(saga_id)
        if not cached:
            raise ValueError(f"Saga '{saga_id}' not found in state cache")

        cached["sse_emitter"] = sse_emitter

        if resume_at == "clarification":
            cached["clarification_answer"] = user_response
            cached["needs_clarification"] = False
        elif resume_at == "tie_breaking":
            cached["tie_breaking_answer"] = user_response
        elif resume_at == "offer_selection":
            ranked = cached.get("ranked_offers", [])
            if selected_offer_index is not None and 0 <= selected_offer_index < len(ranked):
                cached["selected_offer"] = ranked[selected_offer_index]
                if stripe_payment_method_id:
                    cached["stripe_payment_method_id"] = stripe_payment_method_id
                if shipping_address:
                    cached["shipping_address"] = shipping_address
        elif resume_at == "retry_sourcing":
            cached["retry_sourcing"] = True
            cached["all_sourcing_failed"] = False

        try:
            final_state = await self._graph.ainvoke(cached)
            await set_saga_state(saga_id, {k: v for k, v in final_state.items() if k != "sse_emitter" and k != "image_bytes"})
            return final_state
        except Exception as exc:
            logger.exception("orchestrator.resume_error", saga_id=saga_id, error=str(exc))
            raise
