from __future__ import annotations
import requests
from typing import Dict, Any

from config.config import Config
from src.feeds.base import SgpSupport
from src.feeds.models import SgpQuoteRequest, SgpQuoteResponse

class UnabatedSgpAdapter(SgpSupport):
    """
    Adapter for Unabated's SGP pricing and deeplink functionality.
    """
    BASE_URL = "https://api.unabated.com/deeplink/sgp" # This is a guess based on docs, might need adjustment

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or Config.UNABATED_API_KEY
        if not self.api_key:
            raise ValueError("Unabated API key is not configured.")
        self.headers = {"Authorization": f"Bearer {self.api_key}"} # Assuming Bearer token auth

    def _make_request(self, endpoint: str, params: Dict[str, Any]) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def supports_sgp(self) -> bool:
        return True

    def _build_sgp_payload(self, req: SgpQuoteRequest) -> Dict[str, Any]:
        """Translates our SgpQuoteRequest into the provider's format."""
        legs = []
        for leg in req.legs:
            # This is a simplified translation. Unabated uses 'market line ids'.
            # A real implementation would need a mapping from our leg definition
            # to their specific line IDs, which would likely be retrieved from
            # their snapshot or metadata APIs first.
            legs.append({
                "market": leg.market_key.value,
                "outcome": leg.outcome_key,
                "line": leg.line,
            })

        return {
            "book": req.bookmaker,
            "legs": legs,
        }

    def price_sgp(self, req: SgpQuoteRequest) -> SgpQuoteResponse:
        """
        Prices an SGP with the given legs.
        GET /deeplink/sgp/price
        """
        payload = self._build_sgp_payload(req)
        raw_response = self._make_request("/price", params=payload)

        return SgpQuoteResponse(
            bookmaker=req.bookmaker,
            price_american=raw_response.get("priceAmerican"),
            price_decimal=raw_response.get("priceDecimal"),
            valid=raw_response.get("valid", False),
            raw=raw_response,
        )

    def deeplink_sgp(self, req: SgpQuoteRequest) -> SgpQuoteResponse:
        """
        Gets a deeplink URL for an SGP.
        GET /deeplink/sgp
        """
        payload = self._build_sgp_payload(req)
        raw_response = self._make_request("", params=payload) # Assumes base URL is the endpoint

        return SgpQuoteResponse(
            bookmaker=req.bookmaker,
            price_american=None, # Deeplink endpoint might not return price
            price_decimal=None,
            valid=True, # If we get a URL, assume it's valid
            deeplink_url=raw_response.get("deeplinkUrl"),
            raw=raw_response,
        )
