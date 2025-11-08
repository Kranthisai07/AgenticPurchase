"""
LangGraph-based orchestration for the Agentic Purchase saga.

This package allows the system to run fully in-process using LangGraph's
state graph utilities instead of coordinating FastAPI micro-services.
"""

from .orchestrator import (
    build_graph,
    run_saga_async,
    run_saga_preview_async,
    run_saga_sync,
    run_saga_preview_sync,
)

__all__ = [
    "build_graph",
    "run_saga_async",
    "run_saga_preview_async",
    "run_saga_sync",
    "run_saga_preview_sync",
]
