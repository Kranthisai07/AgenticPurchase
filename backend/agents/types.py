"""
AgentType enum and task/result type registry.
Centralises the mapping between agent types and their concrete task + result classes.
"""
from typing import TYPE_CHECKING, Any, Type

from backend.models.agent_messages import AgentType
from backend.models.agent_tasks import (
    CheckoutTask,
    IntentTask,
    RankingTask,
    SourcingTask,
    TrustTask,
    VisionTask,
)
from backend.models.agent_results import (
    CheckoutFailure,
    CheckoutSuccess,
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

# Re-export AgentType so callers only need to import from agents.types
__all__ = ["AgentType", "TASK_TYPES", "RESULT_TYPES"]

TASK_TYPES: dict[AgentType, Type[Any]] = {
    AgentType.VISION: VisionTask,
    AgentType.INTENT: IntentTask,
    AgentType.SOURCING: SourcingTask,
    AgentType.TRUST: TrustTask,
    AgentType.RANKING: RankingTask,
    AgentType.CHECKOUT: CheckoutTask,
}

# Maps agent type → tuple of possible success/failure result classes
RESULT_TYPES: dict[AgentType, tuple[Type[Any], ...]] = {
    AgentType.VISION: (VisionSuccess, VisionFailure),
    AgentType.INTENT: (IntentSuccess, IntentClarification, IntentInjectionDetected),
    AgentType.SOURCING: (SourcingSuccess, SourcingFailure),
    AgentType.TRUST: (TrustSuccess,),
    AgentType.RANKING: (RankingSuccess,),
    AgentType.CHECKOUT: (CheckoutSuccess, CheckoutFailure),
}
