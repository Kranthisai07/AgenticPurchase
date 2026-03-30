"""
FastAPI dependency providers.
All business-layer objects are injected here — never imported directly in routes.
"""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.bus import AgentBus, get_agent_bus
from backend.agents.orchestrator.agent import OrchestratorAgent
from backend.core.database import get_db
from backend.core.redis import get_redis
from backend.core.sse_manager import SSEManager
from backend.core.webhook_processor import WebhookProcessor
from backend.integrations.supermemory.client import SupermemoryClient
from backend.repositories.receipt_repo import ReceiptRepository
from backend.repositories.saga_repo import SagaRepository
from backend.repositories.webhook_repository import WebhookRepository


def get_orchestrator(
    bus: Annotated[AgentBus, Depends(get_agent_bus)],
) -> OrchestratorAgent:
    return OrchestratorAgent(bus=bus)


def get_supermemory() -> SupermemoryClient:
    return SupermemoryClient()


def get_sse_manager() -> SSEManager:
    return SSEManager(redis=get_redis())


def get_webhook_repo(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WebhookRepository:
    return WebhookRepository(db=db)


def get_webhook_processor(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WebhookProcessor:
    return WebhookProcessor(
        sse_manager=SSEManager(redis=get_redis()),
        saga_repo=SagaRepository(db=db),
        receipt_repo=ReceiptRepository(db=db),
        redis=get_redis(),
        supermemory=SupermemoryClient(),
        webhook_repo=WebhookRepository(db=db),
    )
