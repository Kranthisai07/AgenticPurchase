"""
Conditional edge logic for the Orchestrator LangGraph.
Each function returns the name of the next node.
"""
import structlog

from backend.agents.orchestrator.state import OrchestratorState

logger = structlog.get_logger(__name__)


def after_vision(state: OrchestratorState) -> str:
    """Vision always proceeds to intent (even on failure, we use text fallback)."""
    return "intent"


def after_intent(state: OrchestratorState) -> str:
    if state.get("terminal_error"):
        return "end_failed"
    if state.get("needs_clarification"):
        return "await_clarification"
    return "sourcing"


def after_clarification_received(state: OrchestratorState) -> str:
    """After user answers clarification, re-run intent."""
    return "intent"


def after_sourcing(state: OrchestratorState) -> str:
    if state.get("all_sourcing_failed"):
        return "end_no_results"
    return "trust"


_TRUST_MAX_RETRIES = 2


def after_trust(state: OrchestratorState) -> str:
    """
    Compensating edge: when all offers are HIGH_RISK, automatically re-trigger
    sourcing (up to _TRUST_MAX_RETRIES times) with an incremented retry counter
    so the Sourcing Agent can widen its parameters.

    After exhausting retries, fall through to ranking with the best available
    (still high-risk) offers — the UI will surface trust warnings to the user.
    """
    all_high_risk = state.get("all_high_risk", False)
    retry_count   = state.get("trust_retry_count", 0)

    if all_high_risk and retry_count < _TRUST_MAX_RETRIES:
        state["trust_retry_count"] = retry_count + 1
        logger.warning(
            "trust.compensating_edge_triggered",
            retry_count=retry_count + 1,
            max_retries=_TRUST_MAX_RETRIES,
        )
        return "sourcing"

    # Retries exhausted or not all high-risk — proceed to ranking
    state["trust_retry_count"] = 0
    return "ranking"


def after_high_risk_warning(state: OrchestratorState) -> str:
    """After warning user about high-risk sellers."""
    if state.get("retry_sourcing"):
        return "sourcing"
    return "ranking"


def after_ranking(state: OrchestratorState) -> str:
    if state.get("terminal_error"):
        return "end_failed"
    if state.get("near_tie_detected") and not state.get("tie_breaking_answer"):
        return "await_tie_breaking"
    return "await_offer_selection"


def after_tie_breaking_received(state: OrchestratorState) -> str:
    return "ranking"


def after_offer_selection(state: OrchestratorState) -> str:
    if not state.get("selected_offer"):
        return "await_offer_selection"
    return "checkout"


def after_checkout(state: OrchestratorState) -> str:
    if state.get("saga_status") and state["saga_status"].value == "complete":
        return "end_success"
    if state.get("retry_checkout"):
        return "checkout"
    return "end_failed"
