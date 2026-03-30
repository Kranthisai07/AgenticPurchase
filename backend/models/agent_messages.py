from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field
import uuid


class AgentType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    VISION = "vision"
    INTENT = "intent"
    SOURCING = "sourcing"
    TRUST = "trust"
    RANKING = "ranking"
    CHECKOUT = "checkout"


class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    saga_id: str
    from_agent: AgentType
    to_agent: AgentType
    task: Any  # typed concrete task via agent_tasks.py
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    timeout_seconds: int


class AgentResult(BaseModel):
    message_id: str  # echoes the originating task message_id
    saga_id: str
    agent_type: AgentType
    status: Literal["success", "failure", "clarification_needed"]
    result: Any  # typed concrete result via agent_results.py
    error_code: str | None = None
    completed_at: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: int
    tokens_used: int | None = None
    tools_called: list[str] = []
