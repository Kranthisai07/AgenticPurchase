"""
EbayClient — wraps the eBay Browse API and Feedback API.
Provides ebay_search() and ebay_get_seller_feedback() as injectable tools.
"""
from typing import Any

import httpx

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.integrations.base_client import BaseAPIClient

logger = get_logger(__name__)

EBAY_AUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"


class EbayClient(BaseAPIClient):
    vendor = "ebay"

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(base_url=settings.ebay_base_url)
        self._settings = settings
        self._access_token: str | None = None

    async def _ensure_token(self) -> None:
        """Obtain a client credentials OAuth2 token from eBay."""
        if self._access_token:
            return
        import base64

        credentials = base64.b64encode(
            f"{self._settings.ebay_app_id}:{self._settings.ebay_cert_id}".encode()
        ).decode()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                EBAY_AUTH_URL,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {credentials}",
                },
                data={
                    "grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope",
                },
            )
            response.raise_for_status()
            self._access_token = response.json().get("access_token")

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def ebay_search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search eBay items using Browse API."""
        await self._ensure_token()

        params: dict[str, Any] = {
            "q": query,
            "limit": 25,
        }
        filter_parts = []
        if filters:
            if filters.get("min_price") is not None:
                filter_parts.append(f"price:[{filters['min_price']}]")
            if filters.get("max_price") is not None:
                filter_parts.append(f"price:[..{filters['max_price']}]")
            if filters.get("condition") == "new":
                filter_parts.append("conditions:{NEW}")
        if filter_parts:
            params["filter"] = ",".join(filter_parts)

        logger.debug("ebay.search", query=query, params=params)
        response = await self.get("/buy/browse/v1/item_summary/search", params=params)
        return response.get("itemSummaries", [])

    async def ebay_get_seller_feedback(self, username: str) -> dict[str, Any]:
        """Fetch seller feedback for trust scoring."""
        await self._ensure_token()
        logger.debug("ebay.get_seller_feedback", username=username)
        # eBay feedback via Browse API item endpoint — seller info embedded
        response = await self.get(
            f"/buy/browse/v1/item_summary/search",
            params={"q": "", "seller": username, "limit": 1},
        )
        items = response.get("itemSummaries", [])
        if items:
            seller = items[0].get("seller", {})
            return {
                "username": username,
                "feedback_score": seller.get("feedbackScore", 0),
                "feedback_percentage": seller.get("positiveFeedbackPercent", None),
            }
        return {"username": username}
