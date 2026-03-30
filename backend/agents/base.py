"""
BaseAgent — the abstract base class for every executor agent.

Responsibilities:
- Enforce timeout via asyncio.wait_for
- Structured logging with saga_id context (via structlog context vars)
- Token counting and tools_called tracking
- Wrap raw _execute() output into AgentResult
- Call _self_evaluate() before returning success
- Catch and convert all exceptions to failure AgentResult
- Record Prometheus metrics (AGENT_SUCCESS, AGENT_FAILURE, AGENT_TIMEOUT, AGENT_DURATION)
- Create OpenTelemetry spans per agent invocation
"""
import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import structlog

from backend.core.logging import bind_request_context
from backend.core.metrics import AGENT_DURATION, AGENT_FAILURE, AGENT_SUCCESS, AGENT_TIMEOUT
from backend.core.telemetry import get_tracer, record_agent_invocation
from backend.models.agent_messages import AgentResult, AgentType

# One tracer per module — created once at import time, not per invocation
_tracer = get_tracer(__name__)


class BaseAgent(ABC):
    agent_type: AgentType
    timeout: int  # seconds

    def __init__(self, llm: Any | None = None, tools: list[Any] | None = None) -> None:
        self.llm = llm
        self.tools = tools or []
        self._logger = structlog.get_logger(self.__class__.__name__)
        self._tokens_this_run: int = 0  # reset at the start of every run() call

    async def _invoke_llm(self, messages: list[Any]) -> Any:
        """
        Thin wrapper around self.llm.ainvoke() that extracts token usage
        from the response's usage_metadata and accumulates it on
        self._tokens_this_run.  Failures in token extraction never propagate.
        """
        response = await self.llm.ainvoke(messages)
        try:
            usage = getattr(response, "usage_metadata", None) or {}
            tokens = usage.get("total_tokens") or 0
            self._tokens_this_run += int(tokens)
        except Exception:
            pass  # never crash a saga over token counting
        return response

    async def run(self, task: Any, *, message_id: str, saga_id: str) -> AgentResult:
        """
        Public entry point. Enforces timeout, logs, records metrics, creates OTel span.
        Subclasses implement _execute() and _self_evaluate().
        """
        start = time.monotonic()
        agent_label = self.agent_type.value
        self._tokens_this_run = 0  # reset per invocation

        # Bind agent context vars so all nested log calls automatically include
        # agent and saga_id without manual .bind() at each call site.
        bind_request_context(
            agent=agent_label,
            saga_id=saga_id,
        )

        bound_log = self._logger.bind(
            agent=agent_label,
            saga_id=saga_id,
            message_id=message_id,
        )
        bound_log.info("agent.started")

        with _tracer.start_as_current_span(agent_label) as span:
            span.set_attribute("agent.type", agent_label)
            span.set_attribute("agent.saga_id", saga_id)

            try:
                raw_result = await asyncio.wait_for(
                    self._execute(task),
                    timeout=self.timeout,
                )

                # Self-evaluation gate
                ok, reason = await self._self_evaluate(raw_result)
                if not ok:
                    duration_ms = int((time.monotonic() - start) * 1000)
                    bound_log.warning("agent.self_eval_failed", reason=reason, duration_ms=duration_ms)
                    record_agent_invocation(agent_label, "self_eval_failed", duration_ms / 1000)
                    AGENT_FAILURE.labels(
                        agent_type=agent_label,
                        error_code="self_evaluation_failed",
                    ).inc()
                    AGENT_DURATION.labels(agent_type=agent_label).observe(duration_ms / 1000)
                    span.set_attribute("agent.success", False)
                    span.set_attribute("agent.tokens_used", self._tokens_this_run)
                    return AgentResult(
                        message_id=message_id,
                        saga_id=saga_id,
                        agent_type=self.agent_type,
                        status="failure",
                        result=raw_result,
                        error_code="self_evaluation_failed",
                        completed_at=datetime.utcnow(),
                        duration_ms=duration_ms,
                        tokens_used=self._tokens_this_run or None,
                        tools_called=getattr(raw_result, "_tools_called", []),
                    )

                duration_ms = int((time.monotonic() - start) * 1000)
                status = self._resolve_status(raw_result)
                tokens_used = self._tokens_this_run or None
                # GPT-4o blended rate: 85% input ($5/1M) + 15% output ($15/1M)
                # = $6.50/1M tokens = $0.0000065 per token
                # Matches the rate used in backend/evaluation/run_eval.py (_BLENDED_RATE).
                estimated_cost_usd = round(self._tokens_this_run * 0.0000065, 6) if self._tokens_this_run else None

                bound_log.info(
                    "agent.completed",
                    status=status,
                    duration_ms=duration_ms,
                    tokens_used=tokens_used,
                    estimated_cost_usd=estimated_cost_usd,
                )
                record_agent_invocation(agent_label, "success", duration_ms / 1000)

                span.set_attribute("agent.success", True)
                span.set_attribute("agent.tokens_used", self._tokens_this_run)

                if status == "success":
                    AGENT_SUCCESS.labels(agent_type=agent_label).inc()
                elif status == "failure":
                    error_code = (
                        raw_result.get("error", "unknown")
                        if isinstance(raw_result, dict)
                        else getattr(raw_result, "error", "unknown")
                    )
                    AGENT_FAILURE.labels(
                        agent_type=agent_label,
                        error_code=str(error_code),
                    ).inc()

                AGENT_DURATION.labels(agent_type=agent_label).observe(duration_ms / 1000)

                return AgentResult(
                    message_id=message_id,
                    saga_id=saga_id,
                    agent_type=self.agent_type,
                    status=status,
                    result=raw_result,
                    completed_at=datetime.utcnow(),
                    duration_ms=duration_ms,
                    tokens_used=tokens_used,
                    tools_called=getattr(raw_result, "_tools_called", []),
                )

            except asyncio.TimeoutError:
                duration_ms = int((time.monotonic() - start) * 1000)
                bound_log.error("agent.timeout", timeout=self.timeout, duration_ms=duration_ms)
                record_agent_invocation(agent_label, "timeout", duration_ms / 1000)
                AGENT_TIMEOUT.labels(agent_type=agent_label).inc()
                AGENT_FAILURE.labels(agent_type=agent_label, error_code="timeout").inc()
                AGENT_DURATION.labels(agent_type=agent_label).observe(duration_ms / 1000)
                span.set_attribute("agent.success", False)
                span.set_attribute("agent.tokens_used", self._tokens_this_run)
                return AgentResult(
                    message_id=message_id,
                    saga_id=saga_id,
                    agent_type=self.agent_type,
                    status="failure",
                    result=None,
                    error_code="timeout",
                    completed_at=datetime.utcnow(),
                    duration_ms=duration_ms,
                )

            except Exception as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                bound_log.exception("agent.error", error=str(exc), duration_ms=duration_ms)
                record_agent_invocation(agent_label, "error", duration_ms / 1000)
                AGENT_FAILURE.labels(
                    agent_type=agent_label,
                    error_code=type(exc).__name__,
                ).inc()
                AGENT_DURATION.labels(agent_type=agent_label).observe(duration_ms / 1000)
                span.set_attribute("agent.success", False)
                span.record_exception(exc)
                return AgentResult(
                    message_id=message_id,
                    saga_id=saga_id,
                    agent_type=self.agent_type,
                    status="failure",
                    result=None,
                    error_code=type(exc).__name__,
                    completed_at=datetime.utcnow(),
                    duration_ms=duration_ms,
                )

    @abstractmethod
    async def _execute(self, task: Any) -> Any:
        """Core agent logic. Override in every subclass."""

    @abstractmethod
    async def _self_evaluate(self, result: Any) -> tuple[bool, str]:
        """
        Evaluate whether the result is acceptable.
        Returns (True, "") on pass, (False, reason) on fail.
        """

    def _resolve_status(self, result: Any) -> str:
        """Determine AgentResult.status from the result type name."""
        name = type(result).__name__
        if "Failure" in name:
            return "failure"
        if "Clarification" in name:
            return "clarification_needed"
        if "InjectionDetected" in name:
            return "success"  # injection was handled, proceed with sanitized input
        return "success"
