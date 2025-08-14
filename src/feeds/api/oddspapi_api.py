from __future__ import annotations
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

from src.config import Config
from src.feeds.base import OddsFeed
from src.feeds.models import (
    SportKey,
    MarketKey,
    Event,
    EventOdds,
    Bookmaker,
    Competitor,
    Market,
    OutcomePrice,
    Period,
)
from src.feeds.query import FeedQuery

class OddsPapiApiAdapter(OddsFeed):
    """
    Adapter for the OddsPapi REST API (v2).
    Implementation is based on the OpenAPI spec found at /apispec_1.json.
    """
    BASE_URL = "https://api-v2.oddspapi.io/api/v2"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or Config.ODDSPAPI_CLIENT_API_KEY
        if not self.api_key:
            raise ValueError("OddsPapi API key is not configured.")

    def _make_request(self, endpoint: str, params: Dict[str, Any] | None = None) -> Any:
        url = f"{self.BASE_URL}/{endpoint}"
        all_params = {"API-Key": self.api_key}
        if params:
            all_params.update(params)

        response = requests.get(url, params=all_params)
        response.raise_for_status()
        return response.json()

    def list_sports(self) -> List[Dict]: # Returning raw dicts for now
        """Corresponds to GET /sports"""
        return self._make_request("sports")

    def list_bookmakers(self) -> List[Bookmaker]:
        """Corresponds to GET /bookmakers"""
        raw_bookmakers = self._make_request("bookmakers")
        return [Bookmaker(key=b['bookmakerSlug'], title=b['bookmakerName']) for b in raw_bookmakers]

    def list_markets(self, sport: SportKey | None = None) -> List[Dict]:
        """Corresponds to GET /markets"""
        params = {}
        if sport:
            # This would require a mapping from SportKey to oddspapi's sportId
            pass
        return self._make_request("markets", params=params)

    def get_events(self, q: FeedQuery) -> List[Event]:
        """Corresponds to GET /fixtures"""
        params = {}
        if q.sport:
            # Requires sportId mapping
            pass

        raw_data = self._make_request("fixtures", params=params)

        all_events = []
        # The response is nested, so we need to iterate through it
        for sport_info in raw_data:
            for tournament in sport_info.get("tournaments", []):
                for fixture in tournament.get("fixtures", []):
                    all_events.append(self._normalize_event(fixture, tournament))
        return all_events

    def get_odds(self, q: FeedQuery) -> List[EventOdds]:
        # This is complex as odds are per-fixture. A full implementation
        # would first get fixtures, then get odds for each.
        # This is a simplified placeholder.
        raise NotImplementedError("get_odds for OddsPapi requires multiple calls and is not implemented.")

    def get_event_odds(self, event_id: str, q: FeedQuery) -> EventOdds:
        """Corresponds to GET /odds"""
        if not q.bookmakers:
            raise ValueError("Bookmakers must be specified for get_event_odds.")

        params = {
            "fixtureId": event_id,
            "bookmakers": ",".join(q.bookmakers),
        }
        raw_odds = self._make_request("odds", params=params)
        # To normalize this, we'd also need the fixture data itself.
        # This shows the API design requires careful handling.
        raise NotImplementedError

    def _normalize_event(self, raw_fixture: Dict[str, Any], raw_tournament: Dict[str, Any]) -> Event:
        """Normalizes a fixture from the /fixtures endpoint into an Event."""
        # This requires a mapping from oddspapi sportName/sportId to our SportKey
        # sport_key = self.SPORT_MAP.get(raw_tournament["sportName"])

        competitors = [
            Competitor(name=raw_fixture["participant1Name"], role="home"),
            Competitor(name=raw_fixture["participant2Name"], role="away"),
        ]

        return Event(
            event_id=raw_fixture["fixtureId"],
            sport_key=SportKey.NFL, # Placeholder
            league=raw_tournament.get("tournamentName"),
            start_time=datetime.fromtimestamp(raw_fixture["startTime"]),
            status="upcoming", # Assuming all fixtures are upcoming
            competitors=competitors,
        )

    def _normalize_event_odds(self, raw_event: Dict[str, Any], raw_odds: Dict[str, Any], q: FeedQuery) -> EventOdds:
        raise NotImplementedError
