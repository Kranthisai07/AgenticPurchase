"""
SerpApiClient — wraps SerpApi's Google Shopping engine.
Provides google_shopping_search() as an injectable tool.
"""
from typing import Any

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.integrations.base_client import BaseAPIClient

logger = get_logger(__name__)


class SerpApiClient(BaseAPIClient):
    vendor = "serpapi"

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(base_url=settings.serpapi_base_url)
        self._api_key = settings.serpapi_key

    async def google_shopping_search(self, query: str) -> list[dict[str, Any]]:
        """Search Google Shopping via SerpApi."""
        params: dict[str, Any] = {
            "engine": "google_shopping",
            "q": query,
            "api_key": self._api_key,
            "num": 20,
            "hl": "en",
            "gl": "us",
        }

        logger.debug("serpapi.search", query=query)
        response = await self.get("/search", params=params)
        return response.get("shopping_results", [])
