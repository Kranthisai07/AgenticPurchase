"""
SupermemoryClient — long-term user preference and purchase history memory.
"""
from typing import Any

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.integrations.base_client import BaseAPIClient

logger = get_logger(__name__)


class SupermemoryClient(BaseAPIClient):
    vendor = "supermemory"

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            base_url=settings.supermemory_base_url,
            api_key=settings.supermemory_api_key,
        )

    async def get_user_preference(self, user_id: str, preference_key: str) -> Any | None:
        """Retrieve a stored preference value for a user."""
        try:
            response = await self.get(
                f"/v1/memory",
                params={"userId": user_id, "query": preference_key, "limit": 1},
            )
            results = response.get("results", [])
            if results:
                return results[0].get("content")
            return None
        except Exception as exc:
            logger.warning("supermemory.get_preference.failed", user_id=user_id, key=preference_key, error=str(exc))
            return None

    async def store_user_preference(
        self, user_id: str, preference_key: str, value: Any
    ) -> None:
        """Store a preference for a user."""
        try:
            await self.post(
                "/v1/memory",
                json={
                    "userId": user_id,
                    "content": f"{preference_key}: {value}",
                    "metadata": {"type": "preference", "key": preference_key},
                },
            )
        except Exception as exc:
            logger.warning("supermemory.store_preference.failed", user_id=user_id, key=preference_key, error=str(exc))

    async def get_purchase_history(self, user_id: str) -> list[dict[str, Any]]:
        """Retrieve recent purchase context for a user."""
        try:
            response = await self.get(
                "/v1/memory",
                params={"userId": user_id, "query": "purchase history", "limit": 10},
            )
            return response.get("results", [])
        except Exception as exc:
            logger.warning("supermemory.get_history.failed", user_id=user_id, error=str(exc))
            return []

    async def store_purchase(self, user_id: str, receipt_data: dict[str, Any]) -> None:
        """Store a completed purchase for future context."""
        try:
            await self.post(
                "/v1/memory",
                json={
                    "userId": user_id,
                    "content": f"Purchased: {receipt_data.get('title', 'item')} for ${receipt_data.get('amount')}",
                    "metadata": {"type": "purchase", **receipt_data},
                },
            )
        except Exception as exc:
            logger.warning("supermemory.store_purchase.failed", user_id=user_id, error=str(exc))
