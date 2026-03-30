"""
LangGraph node functions for the Orchestrator graph.
Each node calls one or more agents via the AgentBus and updates state.
"""
import asyncio
from typing import Any

import structlog

from backend.agents.bus import get_agent_bus
from backend.agents.orchestrator.state import OrchestratorState
from backend.core.config import get_settings
from backend.models.agent_messages import AgentType
from backend.models.agent_results import (
    IntentClarification,
    IntentInjectionDetected,
    IntentSuccess,
    RankingSuccess,
    SourcingFailure,
    SourcingSuccess,
    TrustSuccess,
    VisionFailure,
    VisionSuccess,
)
from backend.models.agent_tasks import (
    IntentTask,
    RankingTask,
    SourcingTask,
    TrustTask,
    VisionTask,
)
from backend.models.intent import UserPreferences
from backend.models.offer import ScoredOffer
from backend.models.saga import SagaStatus
from backend.models.sse_events import (
    AgentCompletePayload,
    AgentFailedPayload,
    AgentStartedPayload,
    ClarificationNeededPayload,
    OffersReadyPayload,
    SSEEvent,
    SSEEventType,
    TrustScoredPayload,
)

logger = structlog.get_logger(__name__)


async def _emit(state: OrchestratorState, event: SSEEvent) -> None:
    emitter = state.get("sse_emitter")
    if emitter:
        await emitter(event)


def _build_safe_description(attributes: dict) -> str:
    """
    H-05: Build a safe product description from structured attributes only.

    Ignores any free-text product_description that may contain injected
    instructions transcribed by VisionAgent from image text.
    Uses only categorical fields that the vision model extracted as structure.
    """
    parts = [
        attributes.get("category", ""),
        attributes.get("color", ""),
        attributes.get("material", ""),
        attributes.get("style", ""),
    ]
    return " ".join(p for p in parts if p).strip() or "unidentified product"


# ── Node: vision ──────────────────────────────────────────────────────────────

async def node_vision(state: OrchestratorState) -> dict[str, Any]:
    bus = get_agent_bus()
    settings = get_settings()
    saga_id = state["saga_id"]

    await _emit(state, SSEEvent(
        event=SSEEventType.AGENT_STARTED,
        data=AgentStartedPayload(agent="vision", message="Analyzing your image..."),
    ))

    result = await bus.dispatch(
        AgentType.VISION,
        VisionTask(image_bytes=state.get("image_bytes"), user_text=state.get("user_text")),
        saga_id=saga_id,
    )

    if result.status == "failure" or isinstance(result.result, VisionFailure):
        failure = result.result
        await _emit(state, SSEEvent(
            event=SSEEventType.AGENT_FAILED,
            data=AgentFailedPayload(agent="vision", error=getattr(failure, "error", "unknown")),
        ))
        suggestion = getattr(failure, "suggestion", "Please try again.") if failure else "Please try again."
        return {
            "vision_failed": True,
            "vision_failure_suggestion": suggestion,
            "product_description": state.get("user_text", ""),
            "vision_confidence": 0.0,
            "vision_detected_attributes": {},
        }

    success: VisionSuccess = result.result

    # H-05: Check vision output for injected instructions before passing to IntentAgent.
    # An image can contain embedded text with prompt injection instructions that
    # VisionAgent faithfully transcribes into product_description.
    # On detection: sanitize to structured attributes only — do not block the saga
    # (user uploaded a real image; we degrade gracefully to a broader search).
    if success.product_description:
        from backend.core.injection_guard import InjectionGuard
        from langchain_openai import ChatOpenAI

        _guard = InjectionGuard(llm=ChatOpenAI(
            model=settings.openai_model_executor,
            api_key=settings.openai_api_key,
            temperature=0,
        ))
        injection_result = await _guard.check(
            text=success.product_description,
            context="vision_output",
        )
        if injection_result.is_injection and injection_result.confidence >= settings.injection_confidence_threshold:
            logger.warning(
                "vision.output.injection_detected",
                saga_id=saga_id,
                confidence=injection_result.confidence,
                reason=injection_result.reason,
            )
            # Replace free-text with a safe description built from structured attributes
            safe_desc = _build_safe_description(success.detected_attributes)
            success = success.model_copy(update={"product_description": safe_desc})

    await _emit(state, SSEEvent(
        event=SSEEventType.AGENT_COMPLETE,
        data=AgentCompletePayload(agent="vision", duration_ms=result.duration_ms),
    ))
    return {
        "vision_failed": False,
        "product_description": success.product_description,
        "vision_confidence": success.confidence,
        "vision_detected_attributes": success.detected_attributes or {},
    }


# ── Node: intent ──────────────────────────────────────────────────────────────

async def node_intent(state: OrchestratorState) -> dict[str, Any]:
    bus = get_agent_bus()
    saga_id = state["saga_id"]

    await _emit(state, SSEEvent(
        event=SSEEventType.AGENT_STARTED,
        data=AgentStartedPayload(agent="intent", message="Understanding your request..."),
    ))

    # If user provided clarification answer, append it to history
    conv_history = state.get("conversation_history", [])

    result = await bus.dispatch(
        AgentType.INTENT,
        IntentTask(
            product_description=state.get("product_description", ""),
            user_text=state.get("clarification_answer") or state.get("user_text"),
            conversation_history=conv_history,
            user_preferences=state.get("user_preferences") or UserPreferences(),
        ),
        saga_id=saga_id,
    )

    if result.status == "clarification_needed" or isinstance(result.result, IntentClarification):
        clarification: IntentClarification = result.result
        await _emit(state, SSEEvent(
            event=SSEEventType.CLARIFICATION_NEEDED,
            data=ClarificationNeededPayload(
                questions=clarification.questions,
                partial_intent=clarification.partial_intent.model_dump(),
            ),
        ))
        return {
            "needs_clarification": True,
            "clarification_questions": clarification.questions,
            "parsed_intent": clarification.partial_intent,
            "saga_status": SagaStatus.AWAITING_USER,
        }

    # H-05: IntentInjectionDetected means the LLM classifier blocked the input
    # with high confidence.  Return a user-friendly terminal error so the saga
    # fails cleanly rather than silently proceeding with unsafe input.
    if isinstance(result.result, IntentInjectionDetected):
        await _emit(state, SSEEvent(
            event=SSEEventType.AGENT_FAILED,
            data=AgentFailedPayload(agent="intent", error="injection_blocked"),
        ))
        return {
            "terminal_error": result.result.proceeds_with,
            "saga_status": SagaStatus.FAILED,
        }

    if result.status == "failure" or result.result is None:
        await _emit(state, SSEEvent(
            event=SSEEventType.AGENT_FAILED,
            data=AgentFailedPayload(agent="intent", error="parsing_failed"),
        ))
        return {
            "terminal_error": "I couldn't understand your request. Please rephrase.",
            "saga_status": SagaStatus.FAILED,
        }

    success: IntentSuccess = result.result if isinstance(result.result, IntentSuccess) else IntentSuccess(parsed_intent=result.result.partial_intent if hasattr(result.result, "partial_intent") else state.get("parsed_intent"))

    await _emit(state, SSEEvent(
        event=SSEEventType.AGENT_COMPLETE,
        data=AgentCompletePayload(agent="intent", duration_ms=result.duration_ms),
    ))
    return {
        "needs_clarification": False,
        "parsed_intent": success.parsed_intent,
        "clarification_answer": None,
        "saga_status": SagaStatus.INTENT,
    }


# ── Node: sourcing (parallel) ─────────────────────────────────────────────────

async def node_sourcing(state: OrchestratorState) -> dict[str, Any]:
    bus = get_agent_bus()
    settings = get_settings()
    saga_id = state["saga_id"]
    intent = state["parsed_intent"]

    for source in ["ebay", "serpapi"]:
        await _emit(state, SSEEvent(
            event=SSEEventType.AGENT_STARTED,
            data=AgentStartedPayload(agent=f"sourcing_{source}", message=f"Searching {source.capitalize()}..."),
        ))

    results = await bus.dispatch_parallel(
        [
            (AgentType.SOURCING, SourcingTask(source="ebay", parsed_intent=intent)),
            (AgentType.SOURCING, SourcingTask(source="serpapi", parsed_intent=intent)),
        ],
        timeout=settings.sourcing_agent_timeout,
        aggregate_timeout=settings.sourcing_aggregate_timeout,
        saga_id=saga_id,
    )

    all_offers = []
    failures = []

    for result in results:
        if isinstance(result.result, SourcingSuccess):
            all_offers.extend(result.result.offers)
            await _emit(state, SSEEvent(
                event=SSEEventType.AGENT_COMPLETE,
                data=AgentCompletePayload(agent=f"sourcing_{result.result.source}", duration_ms=result.duration_ms),
            ))
        elif isinstance(result.result, SourcingFailure):
            failures.append(result.result.source)
            await _emit(state, SSEEvent(
                event=SSEEventType.AGENT_FAILED,
                data=AgentFailedPayload(agent=f"sourcing_{result.result.source}", error=result.result.error),
            ))
        elif isinstance(result.result, dict) and result.result.get("error") == "aggregate_timeout":
            failures.append("timeout")
        else:
            failures.append("unknown")

    # H-03: detect partial timeouts and log for observability
    timed_out = [
        r for r in results
        if isinstance(r.result, dict) and r.result.get("error") == "aggregate_timeout"
    ]
    if timed_out and all_offers:
        logger.warning(
            "sourcing.partial_timeout",
            saga_id=saga_id,
            timed_out_count=len(timed_out),
            successful_count=len(results) - len(timed_out),
        )

    return {
        "all_offers": all_offers,
        "sourcing_failures": failures,
        "all_sourcing_failed": len(all_offers) == 0,
        "saga_status": SagaStatus.SOURCING,
        "retry_sourcing": False,
    }


# ── Node: trust (parallel per source batch) ───────────────────────────────────

async def node_trust(state: OrchestratorState) -> dict[str, Any]:
    bus = get_agent_bus()
    settings = get_settings()
    saga_id = state["saga_id"]
    all_offers = state.get("all_offers", [])

    if not all_offers:
        return {"scored_offers": [], "all_high_risk": False, "all_insufficient": False}

    # Group by source
    by_source: dict[str, list] = {"ebay": [], "serpapi": []}
    for offer in all_offers:
        by_source[offer.source].append(offer)

    vision_attrs = state.get("vision_detected_attributes") or {}
    product_desc = state.get("product_description") or ""

    tasks = [
        (AgentType.TRUST, TrustTask(
            offers=offers,
            source=source,
            vision_attributes=vision_attrs,
            product_description=product_desc,
        ))
        for source, offers in by_source.items()
        if offers
    ]

    await _emit(state, SSEEvent(
        event=SSEEventType.AGENT_STARTED,
        data=AgentStartedPayload(agent="trust", message="Evaluating seller trust..."),
    ))

    results = await bus.dispatch_parallel(
        tasks,
        timeout=settings.trust_agent_timeout,
        aggregate_timeout=settings.trust_aggregate_timeout,
        saga_id=saga_id,
    )

    scored: list[ScoredOffer] = []
    for result in results:
        if isinstance(result.result, TrustSuccess):
            scored.extend(result.result.scored_offers)
            # Emit per-offer trust events
            for offer in result.result.scored_offers:
                await _emit(state, SSEEvent(
                    event=SSEEventType.TRUST_SCORED,
                    data=TrustScoredPayload(
                        offer_id=offer.offer_id,
                        trust_level=offer.trust_score.level,
                        explanation=offer.trust_score.explanation,
                    ),
                ))
        elif isinstance(result.result, dict) and result.result.get("error") == "aggregate_timeout":
            logger.warning(
                "trust.aggregate_timeout",
                saga_id=saga_id,
            )

    from backend.models.trust import TrustLevel
    all_high_risk = bool(scored) and all(
        o.trust_score.level == TrustLevel.HIGH_RISK for o in scored
    )
    all_insufficient = bool(scored) and all(
        o.trust_score.level == TrustLevel.INSUFFICIENT_DATA for o in scored
    )

    await _emit(state, SSEEvent(
        event=SSEEventType.AGENT_COMPLETE,
        data=AgentCompletePayload(agent="trust", duration_ms=0),
    ))

    return {
        "scored_offers": scored,
        "all_high_risk": all_high_risk,
        "all_insufficient": all_insufficient,
        "saga_status": SagaStatus.TRUST,
    }


# ── Node: ranking ─────────────────────────────────────────────────────────────

async def node_ranking(state: OrchestratorState) -> dict[str, Any]:
    bus = get_agent_bus()
    saga_id = state["saga_id"]

    await _emit(state, SSEEvent(
        event=SSEEventType.AGENT_STARTED,
        data=AgentStartedPayload(agent="ranking", message="Ranking the best offers for you..."),
    ))

    result = await bus.dispatch(
        AgentType.RANKING,
        RankingTask(
            scored_offers=state.get("scored_offers", []),
            parsed_intent=state["parsed_intent"],
            user_preferences=state.get("user_preferences") or UserPreferences(),
        ),
        saga_id=saga_id,
    )

    if result.status == "failure" or not isinstance(result.result, RankingSuccess):
        return {"terminal_error": "Ranking failed.", "saga_status": SagaStatus.FAILED}

    ranking: RankingSuccess = result.result

    await _emit(state, SSEEvent(
        event=SSEEventType.OFFERS_READY,
        data=OffersReadyPayload(
            offers=ranking.ranked_offers,
            ranking_explanation=ranking.ranking_explanation,
        ),
    ))
    await _emit(state, SSEEvent(
        event=SSEEventType.AGENT_COMPLETE,
        data=AgentCompletePayload(agent="ranking", duration_ms=result.duration_ms),
    ))

    return {
        "ranked_offers": ranking.ranked_offers,
        "ranking_explanation": ranking.ranking_explanation,
        "near_tie_detected": ranking.near_tie_detected,
        "near_tie_question": ranking.near_tie_question,
        "saga_status": SagaStatus.RANKING,
    }


# ── Node: checkout ────────────────────────────────────────────────────────────

async def node_checkout(state: OrchestratorState) -> dict[str, Any]:
    from backend.agents.bus import get_agent_bus
    from backend.models.agent_tasks import CheckoutTask
    from backend.models.agent_results import CheckoutSuccess, CheckoutFailure
    from backend.models.sse_events import CheckoutReadyPayload, SagaCompletePayload, SagaFailedPayload

    bus = get_agent_bus()
    saga_id = state["saga_id"]
    offer = state["selected_offer"]

    await _emit(state, SSEEvent(
        event=SSEEventType.AGENT_STARTED,
        data=AgentStartedPayload(agent="checkout", message="Processing your payment..."),
    ))

    result = await bus.dispatch(
        AgentType.CHECKOUT,
        CheckoutTask(
            saga_id=saga_id,
            selected_offer=offer,
            stripe_payment_method_id=state.get("stripe_payment_method_id", ""),
            shipping_address=state.get("shipping_address"),
            user_id=state["user_id"],
        ),
        saga_id=saga_id,
    )

    if isinstance(result.result, CheckoutSuccess):
        success: CheckoutSuccess = result.result
        await _emit(state, SSEEvent(
            event=SSEEventType.CHECKOUT_READY,
            data=CheckoutReadyPayload(
                client_secret=success.client_secret,
                amount=offer.price.amount,
                currency=offer.price.currency,
            ),
        ))
        await _emit(state, SSEEvent(
            event=SSEEventType.SAGA_COMPLETE,
            data=SagaCompletePayload(
                receipt_id=success.receipt_id,
                summary=f"Purchase initiated for '{offer.title}'.",
            ),
        ))
        return {
            "checkout_client_secret": success.client_secret,
            "receipt_id": success.receipt_id,
            "saga_status": SagaStatus.COMPLETE,
            "retry_checkout": False,
        }

    failure: CheckoutFailure = result.result
    await _emit(state, SSEEvent(
        event=SSEEventType.SAGA_FAILED,
        data=SagaFailedPayload(
            reason=failure.error,
            user_message=failure.user_message,
            retry_allowed=failure.retry_allowed,
        ),
    ))
    return {
        "checkout_error": failure.user_message,
        "checkout_retry_allowed": failure.retry_allowed,
        "saga_status": SagaStatus.FAILED if not failure.retry_allowed else SagaStatus.CHECKOUT,
        "retry_checkout": failure.retry_allowed,
    }
