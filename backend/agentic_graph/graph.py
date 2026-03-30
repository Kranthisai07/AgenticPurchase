from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import (
    capture_node,
    checkout_node,
    intent_node,
    sourcing_node,
    trust_node,
)
from .state import SagaState


def build_graph(*, include_checkout: bool = True):
    """Create and compile the LangGraph saga."""
    graph = StateGraph(SagaState)

    graph.add_node("s1_capture", capture_node)
    graph.add_node("s2_intent", intent_node)
    graph.add_node("s3_sourcing", sourcing_node)
    graph.add_node("s4_trust", trust_node)
    if include_checkout:
        graph.add_node("s5_checkout", checkout_node)

    graph.set_entry_point("s1_capture")
    graph.add_edge("s1_capture", "s2_intent")
    graph.add_edge("s2_intent", "s3_sourcing")
    graph.add_edge("s3_sourcing", "s4_trust")

    if include_checkout:
        graph.add_edge("s4_trust", "s5_checkout")
        graph.add_edge("s5_checkout", END)
    else:
        graph.add_edge("s4_trust", END)

    return graph.compile()
