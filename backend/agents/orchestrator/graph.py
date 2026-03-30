"""
LangGraph state machine definition for the Orchestrator.

The graph wires all nodes together via the conditional edges defined in edges.py.
The Orchestrator does NOT call agent logic directly — it uses nodes.py which
dispatches through AgentBus.
"""
from langgraph.graph import END, START, StateGraph

from backend.agents.orchestrator.edges import (
    after_checkout,
    after_clarification_received,
    after_high_risk_warning,
    after_intent,
    after_offer_selection,
    after_ranking,
    after_sourcing,
    after_tie_breaking_received,
    after_trust,
    after_vision,
)
from backend.agents.orchestrator.nodes import (
    node_checkout,
    node_intent,
    node_ranking,
    node_sourcing,
    node_trust,
    node_vision,
)
from backend.agents.orchestrator.state import OrchestratorState


async def node_await_clarification(state: OrchestratorState) -> dict:
    """Pause node — the graph suspends here waiting for user input via the API."""
    return {}


async def node_warn_high_risk(state: OrchestratorState) -> dict:
    """Emit a high-risk warning SSE and wait for user decision."""
    from backend.agents.orchestrator.state import OrchestratorState
    from backend.models.sse_events import SSEEvent, SSEEventType, SagaFailedPayload

    emitter = state.get("sse_emitter")
    if emitter:
        await emitter(SSEEvent(
            event=SSEEventType.SAGA_FAILED,
            data=SagaFailedPayload(
                reason="all_high_risk",
                user_message=(
                    "All vendors found have low trust scores. "
                    "Would you like me to search with different parameters?"
                ),
                retry_allowed=True,
            ),
        ))
    return {}


async def node_await_tie_breaking(state: OrchestratorState) -> dict:
    """Pause for tie-breaking question response."""
    return {}


async def node_await_offer_selection(state: OrchestratorState) -> dict:
    """Pause for offer selection from user."""
    return {}


async def node_end_success(state: OrchestratorState) -> dict:
    return {}


async def node_end_failed(state: OrchestratorState) -> dict:
    return {}


async def node_end_no_results(state: OrchestratorState) -> dict:
    from backend.models.sse_events import SSEEvent, SSEEventType, SagaFailedPayload
    emitter = state.get("sse_emitter")
    if emitter:
        await emitter(SSEEvent(
            event=SSEEventType.SAGA_FAILED,
            data=SagaFailedPayload(
                reason="no_results",
                user_message=(
                    "I couldn't find products matching your description. "
                    "Try being more specific or broaden the search."
                ),
                retry_allowed=True,
            ),
        ))
    return {}


def build_graph() -> StateGraph:
    graph = StateGraph(OrchestratorState)

    # Register nodes
    graph.add_node("vision", node_vision)
    graph.add_node("intent", node_intent)
    graph.add_node("await_clarification", node_await_clarification)
    graph.add_node("sourcing", node_sourcing)
    graph.add_node("trust", node_trust)
    graph.add_node("warn_high_risk", node_warn_high_risk)
    graph.add_node("ranking", node_ranking)
    graph.add_node("await_tie_breaking", node_await_tie_breaking)
    graph.add_node("await_offer_selection", node_await_offer_selection)
    graph.add_node("checkout", node_checkout)
    graph.add_node("end_success", node_end_success)
    graph.add_node("end_failed", node_end_failed)
    graph.add_node("end_no_results", node_end_no_results)

    # Edges from START
    graph.add_edge(START, "vision")

    # Vision → Intent (always)
    graph.add_conditional_edges("vision", after_vision, {"intent": "intent"})

    # Intent → sourcing or clarification
    graph.add_conditional_edges(
        "intent",
        after_intent,
        {
            "sourcing": "sourcing",
            "await_clarification": "await_clarification",
            "end_failed": "end_failed",
        },
    )

    # Clarification → back to intent
    graph.add_conditional_edges(
        "await_clarification",
        after_clarification_received,
        {"intent": "intent"},
    )

    # Sourcing → trust or no results
    graph.add_conditional_edges(
        "sourcing",
        after_sourcing,
        {"trust": "trust", "end_no_results": "end_no_results"},
    )

    # Trust → ranking  OR  automatic compensating retry to sourcing
    # after_trust() now handles the compensating edge directly:
    #   all_high_risk + retries remaining  → "sourcing"
    #   retries exhausted or not all-risk  → "ranking"
    graph.add_conditional_edges(
        "trust",
        after_trust,
        {"ranking": "ranking", "sourcing": "sourcing"},
    )

    # High-risk warning → retry sourcing or proceed to ranking
    graph.add_conditional_edges(
        "warn_high_risk",
        after_high_risk_warning,
        {"sourcing": "sourcing", "ranking": "ranking"},
    )

    # Ranking → offer selection or tie-breaking
    graph.add_conditional_edges(
        "ranking",
        after_ranking,
        {
            "await_offer_selection": "await_offer_selection",
            "await_tie_breaking": "await_tie_breaking",
            "end_failed": "end_failed",
        },
    )

    # Tie-breaking → re-rank
    graph.add_conditional_edges(
        "await_tie_breaking",
        after_tie_breaking_received,
        {"ranking": "ranking"},
    )

    # Offer selection → checkout
    graph.add_conditional_edges(
        "await_offer_selection",
        after_offer_selection,
        {
            "checkout": "checkout",
            "await_offer_selection": "await_offer_selection",
        },
    )

    # Checkout → success or failure
    graph.add_conditional_edges(
        "checkout",
        after_checkout,
        {
            "end_success": "end_success",
            "end_failed": "end_failed",
            "checkout": "checkout",
        },
    )

    # Terminal nodes → END
    graph.add_edge("end_success", END)
    graph.add_edge("end_failed", END)
    graph.add_edge("end_no_results", END)

    return graph


def compile_graph():
    """Compile the LangGraph state machine."""
    return build_graph().compile()
