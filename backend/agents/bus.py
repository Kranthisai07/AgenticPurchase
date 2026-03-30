"""
AgentBus — the async dispatch layer for all inter-agent communication.

Rules:
- Agents never instantiate each other directly.
- All communication goes through dispatch() or dispatch_parallel().
- Per-agent timeouts are enforced by BaseAgent.run(), not by the bus.
- The bus enforces an aggregate wall-clock budget across all parallel tasks
  via asyncio.wait_for() wrapping the gather (H-03).
- The bus is responsible for routing and result collection only.
"""
import asyncio
import uuid
from datetime import datetime
from typing import Any

import structlog

from backend.agents.base import BaseAgent
from backend.core.exceptions import AgentBusError
from backend.models.agent_messages import AgentMessage, AgentResult, AgentType

logger = structlog.get_logger(__name__)


class AgentBus:
    """
    Registry + dispatcher for all agent instances.
    Agents are registered at application startup and looked up by type.
    """

    def __init__(self) -> None:
        self._registry: dict[AgentType, BaseAgent] = {}
        # Per-saga token accumulator: {saga_id: {agent_name: tokens}}
        # Consumed and cleared by get_saga_tokens() at saga completion.
        self._saga_tokens: dict[str, dict[str, int]] = {}

    def get_saga_tokens(self, saga_id: str) -> dict[str, int]:
        """Return and remove the accumulated per-agent token counts for a saga."""
        return self._saga_tokens.pop(saga_id, {})

    def register(self, agent: BaseAgent) -> None:
        self._registry[agent.agent_type] = agent
        logger.info("agent_bus.registered", agent=agent.agent_type.value)

    def get_agent(self, agent_type: AgentType) -> BaseAgent:
        agent = self._registry.get(agent_type)
        if agent is None:
            raise AgentBusError(
                f"Agent '{agent_type.value}' is not registered in the AgentBus"
            )
        return agent

    async def dispatch(
        self,
        agent_type: AgentType,
        task: Any,
        *,
        saga_id: str,
    ) -> AgentResult:
        """Dispatch a single task to an agent and await its result."""
        agent = self.get_agent(agent_type)
        message_id = str(uuid.uuid4())

        logger.info(
            "agent_bus.dispatch",
            agent=agent_type.value,
            saga_id=saga_id,
            message_id=message_id,
        )

        result = await agent.run(task, message_id=message_id, saga_id=saga_id)

        # Accumulate token counts per saga for cost aggregation at saga completion
        if result.tokens_used:
            saga_bucket = self._saga_tokens.setdefault(saga_id, {})
            saga_bucket[agent_type.value] = (
                saga_bucket.get(agent_type.value, 0) + result.tokens_used
            )

        logger.info(
            "agent_bus.dispatch_complete",
            agent=agent_type.value,
            saga_id=saga_id,
            status=result.status,
            duration_ms=result.duration_ms,
            tokens_used=result.tokens_used,
        )
        return result

    async def dispatch_parallel(
        self,
        tasks: list[tuple[AgentType, Any]],
        timeout: int = 20,
        aggregate_timeout: int = 25,
        *,
        saga_id: str,
    ) -> list[AgentResult]:
        """
        Dispatch multiple tasks concurrently and collect all results.

        H-03: aggregate_timeout enforces a wall-clock budget for ALL tasks
        combined via asyncio.wait_for().  Individual agent failures do NOT
        cancel sibling tasks (return_exceptions=True).  If the aggregate
        budget expires, any incomplete slot is filled with a synthetic
        "aggregate_timeout" failure AgentResult.

        Args:
            tasks: ordered list of (AgentType, task) pairs.
            timeout: per-agent budget in seconds (enforced by BaseAgent.run).
            aggregate_timeout: wall-clock ceiling for the entire gather.
            saga_id: propagated to every child dispatch.

        Returns:
            Full list of AgentResult in the same order as `tasks`.
            Never raises — always returns a complete list.
        """
        logger.info(
            "agent_bus.dispatch_parallel",
            agents=[t[0].value for t in tasks],
            saga_id=saga_id,
            count=len(tasks),
            aggregate_timeout_seconds=aggregate_timeout,
        )

        results: list[AgentResult | None] = [None] * len(tasks)

        async def _run_one(
            agent_type: AgentType, task: Any, index: int
        ) -> tuple[int, AgentResult]:
            result = await self.dispatch(agent_type, task, saga_id=saga_id)
            return index, result

        try:
            completed = await asyncio.wait_for(
                asyncio.gather(
                    *[_run_one(at, t, i) for i, (at, t) in enumerate(tasks)],
                    return_exceptions=True,
                ),
                timeout=aggregate_timeout,
            )
            for item in completed:
                if isinstance(item, Exception):
                    # Individual agent exception already logged by BaseAgent;
                    # leave the slot as None so it gets the timeout sentinel below.
                    logger.error(
                        "agent_bus.dispatch_parallel.exception",
                        saga_id=saga_id,
                        error=str(item),
                    )
                    continue
                index, result = item
                results[index] = result

        except asyncio.TimeoutError:
            logger.warning(
                "agent_bus.aggregate_timeout",
                saga_id=saga_id,
                task_count=len(tasks),
                aggregate_timeout_seconds=aggregate_timeout,
            )

        # Fill any None slots (timed-out or excepted) with failure AgentResults
        for i, (agent_type, task) in enumerate(tasks):
            if results[i] is None:
                results[i] = AgentResult(
                    message_id=str(uuid.uuid4()),
                    saga_id=saga_id,
                    agent_type=agent_type,
                    status="failure",
                    result={
                        "error": "aggregate_timeout",
                        "message": f"Did not complete within {aggregate_timeout}s",
                    },
                    error_code="aggregate_timeout",
                    completed_at=datetime.utcnow(),
                    duration_ms=aggregate_timeout * 1000,
                    tokens_used=None,
                    tools_called=[],
                )

        logger.info(
            "agent_bus.dispatch_parallel_complete",
            saga_id=saga_id,
            statuses=[r.status for r in results],
        )
        return results


# ── Singleton ─────────────────────────────────────────────────────────────────

_bus: AgentBus | None = None


def get_agent_bus() -> AgentBus:
    global _bus
    if _bus is None:
        _bus = AgentBus()
    return _bus
