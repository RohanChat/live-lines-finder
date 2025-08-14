from __future__ import annotations
import json
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

class UnabatedApiAdapter(OddsFeed):
    """
    Adapter for the Unabated REST API (snapshot data).
    """

    def __init__(self, api_key: str | None = None, maps_path: str = "config/unabated_maps.json"):
        self.api_key = api_key or Config.UNABATED_API_KEY
        self.base_url = Config.UNABATED_DATA_API_URL or "https://api.unabated.com/v1"

        if not self.api_key:
            raise ValueError("Unabated API key is not configured.")

        self.headers = {"Authorization": f"Bearer {self.api_key}"} # Assuming Bearer token

        with open(maps_path, 'r') as f:
            self.maps = json.load(f)
        
        self.SPORT_MAP = self.maps.get("SPORT_MAP", {})
        self.MARKET_MAP = self.maps.get("MARKET_TYPE_MAP", {})

    def _make_request(self, endpoint: str, params: Dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def list_sports(self) -> List[SportKey]:
        # Unabated doesn't have a /sports endpoint. The supported sports are
        # derived from the leagues we have mapped.
        return [SportKey(v) for v in self.SPORT_MAP.values()]

    def list_bookmakers(self) -> List[Bookmaker]:
        # Unabated docs mention "marketSourceGroups" or "book" slugs.
        # A full implementation would fetch these from a dedicated endpoint if available,
        # or derive them from odds responses.
        return [
            Bookmaker(key="draftkings", title="DraftKings"),
            Bookmaker(key="fanduel", title="FanDuel"),
        ]

    def list_markets(self, sport: SportKey | None = None) -> List[MarketKey]:
        # Returns the markets we have mapped.
        return [MarketKey(v) for v in self.MARKET_MAP.values()]

    def get_events(self, q: FeedQuery) -> List[Event]:
        if not q.leagues:
            raise ValueError("A league must be specified for get_events with Unabated.")

        all_events = []
        for league in q.leagues:
            raw_events = self._make_request(f"/event/{league}/upcoming")
            all_events.extend([self._normalize_event(e, league) for e in raw_events])
        return all_events

    def get_odds(self, q: FeedQuery) -> List[EventOdds]:
        # Unabated's snapshot endpoint is per-league and per-market.
        # This method would require multiple calls and merging.
        # This is a simplified example for one league and one market type.
        if not q.leagues or not q.markets:
            raise ValueError("A league and at least one market must be specified.")

        league = q.leagues[0]
        market_type = q.markets[0].value # e.g., "h2h"

        reverse_market_map = {v: k for k, v in self.MARKET_MAP.items()}
        market_type_str = reverse_market_map.get(market_type)

        # This is a placeholder for a real snapshot endpoint call
        # e.g., /odds/{league}/{market_type}
        # Since the exact endpoint isn't specified, we can't implement this fully.
        raise NotImplementedError("Unabated snapshot get_odds requires a specific endpoint structure.")

    def get_event_odds(self, event_id: str, q: FeedQuery) -> EventOdds:
        raise NotImplementedError("Unabated API does not support fetching odds by a single event ID in this manner.")

    def _normalize_event(self, raw: Dict[str, Any], league: str) -> Event:
        # Unabated event structure might be different, this is an assumption
        home = next((c for c in raw.get("participants", []) if c["rotation_number"] % 2 != 0), {})
        away = next((c for c in raw.get("participants", []) if c["rotation_number"] % 2 == 0), {})

        competitors = [
            Competitor(name=home.get("team", {}).get("name"), role="home", team_id=str(home.get("team_id"))),
            Competitor(name=away.get("team", {}).get("name"), role="away", team_id=str(away.get("team_id"))),
        ]

        return Event(
            event_id=str(raw["id"]),
            sport_key=SportKey(self.SPORT_MAP.get(league)),
            league=league,
            start_time=datetime.fromisoformat(raw["game_time"]),
            status="upcoming",
            competitors=competitors,
        )

    def _normalize_event_odds(self, raw_event: Dict[str, Any], raw_odds: Dict[str, Any], q: FeedQuery) -> EventOdds:
        # This would parse the complex snapshot response from Unabated, which
        # contains lines from multiple bookmakers for a given market.
        # The structure is not provided in the prompt, so this is a placeholder.
        event = self._normalize_event(raw_event, q.leagues[0])
        return EventOdds(event=event, markets=[])
