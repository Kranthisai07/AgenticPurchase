from __future__ import annotations

from typing import Any, Dict

from .state import SagaState


def state_to_payload(state: SagaState) -> Dict[str, Any]:
    """Convert SagaState into the response payload expected by clients."""
    return {
        "hypothesis": state.hypothesis,
        "intent": state.intent,
        "offers": state.offers or [],
        "offer": state.best_offer,
        "trust": state.trust,
        "receipt": state.receipt,
        "log": list(state.events),
    }
