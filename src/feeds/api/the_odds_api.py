from __future__ import annotations
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

from config.config import Config
from src.feeds.base import OddsFeed
from src.feeds.models import (
    SportKey,
    MarketType,
    Event,
    EventOdds,
    Bookmaker,
    Competitor,
    Market,
    OutcomePrice,
    Period,
)
from src.feeds.query import FeedQuery

def american_to_decimal(american_odds: int) -> float:
    if american_odds > 0:
        return round(1 + (american_odds / 100), 2)
    else:
        return round(1 - (100 / american_odds), 2)

class TheOddsApiAdapter(OddsFeed):
    """
    Adapter for The Odds API (https://the-odds-api.com/).
    """
    BASE_URL = "https://api.the-odds-api.com/v4"

    # Basic mapping from TOA keys to our internal SportKey enum
    SPORT_MAP = {
        "americanfootball_nfl": SportKey.NFL,
        "americanfootball_ncaaf": SportKey.NCAAF,
        "basketball_nba": SportKey.NBA,
        "basketball_ncaab": SportKey.NCAAB,
        "baseball_mlb": SportKey.MLB,
        "icehockey_nhl": SportKey.NHL,
    }

    MARKET_MAP = {
        "h2h": MarketType.H2H,
        "spreads": MarketType.SPREAD,
        "totals": MarketType.TOTAL,
    }

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or Config.ODDS_API_KEY
        if not self.api_key:
            raise ValueError("TheOddsAPI API key is not configured.")

    def _make_request(self, endpoint: str, params: Dict[str, Any] | None = None) -> Any:
        url = f"{self.BASE_URL}/{endpoint}"
        all_params = {"apiKey": self.api_key}
        if params:
            all_params.update(params)

        response = requests.get(url, params=all_params)
        response.raise_for_status()  # Raise an exception for bad status codes
        return response.json()

    def list_sports(self) -> List[SportKey]:
        raw_sports = self._make_request("sports")
        return [self.SPORT_MAP[s["key"]] for s in raw_sports if s["key"] in self.SPORT_MAP]

    def list_bookmakers(self) -> List[Bookmaker]:
        # The Odds API doesn't have a dedicated bookmaker endpoint.
        # This would typically be derived from get_odds calls.
        # For now, we return a hardcoded list based on common US books.
        # A better implementation would dynamically build this.
        return [
            Bookmaker(key="draftkings", title="DraftKings"),
            Bookmaker(key="fanduel", title="FanDuel"),
            Bookmaker(key="betmgm", title="BetMGM"),
        ]

    def list_markets(self, sport: SportKey | None = None) -> List[MarketType]:
        # Returns the featured markets that are most common.
        return [MarketType.H2H, MarketType.SPREAD, MarketType.TOTAL]

    def get_events(self, q: FeedQuery) -> List[Event]:
        if not q.sport:
            raise ValueError("A sport must be specified for get_events.")

        reverse_sport_map = {v: k for k, v in self.SPORT_MAP.items()}
        sport_key_str = reverse_sport_map.get(q.sport)

        params = {"dateFormat": "iso"}
        if q.start_time_from:
            params["commenceTimeFrom"] = q.start_time_from.isoformat()

        raw_events = self._make_request(f"sports/{sport_key_str}/events", params)
        return [self._normalize_event(e) for e in raw_events]

    def get_odds(self, q: FeedQuery) -> List[EventOdds]:
        if not q.sport:
            raise ValueError("A sport must be specified for get_odds.")

        reverse_sport_map = {v: k for k, v in self.SPORT_MAP.items()}
        sport_key_str = reverse_sport_map.get(q.sport)

        params = {
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
            "dateFormat": "iso",
        }
        if q.regions:
            params["regions"] = ",".join(q.regions)
        if q.markets:
            reverse_market_map = {v: k for k, v in self.MARKET_MAP.items()}
            params["markets"] = ",".join([reverse_market_map[m] for m in q.markets])

        raw_odds_data = self._make_request(f"sports/{sport_key_str}/odds", params)
        return [self._normalize_event_odds(raw_event, raw_event, q) for raw_event in raw_odds_data]


    def get_event_odds(self, event_id: str, q: FeedQuery) -> EventOdds:
        if not q.sport:
            raise ValueError("A sport must be specified for get_event_odds.")

        reverse_sport_map = {v: k for k, v in self.SPORT_MAP.items()}
        sport_key_str = reverse_sport_map.get(q.sport)

        params = {
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
            "dateFormat": "iso",
        }

        raw_event_with_odds = self._make_request(f"sports/{sport_key_str}/events/{event_id}/odds", params)
        return self._normalize_event_odds(raw_event_with_odds, raw_event_with_odds, q)

    def _normalize_event(self, raw: Dict[str, Any]) -> Event:
        competitors = [
            Competitor(name=raw["home_team"], role="home"),
            Competitor(name=raw["away_team"], role="away"),
        ]
        return Event(
            event_id=raw["id"],
            sport_key=self.SPORT_MAP.get(raw["sport_key"], raw["sport_key"]),
            league=raw.get("sport_league"),
            start_time=datetime.fromisoformat(raw["commence_time"].replace("Z", "+00:00")),
            status="upcoming",  # TOA doesn't provide a clear status field in this context
            competitors=competitors,
        )

    def _normalize_event_odds(self, raw_event: Dict[str, Any], raw_odds: Dict[str, Any], q: FeedQuery) -> EventOdds:
        event = self._normalize_event(raw_event)

        markets = {} # Group by market_key

        for bookmaker in raw_odds.get("bookmakers", []):
            book_key = bookmaker["key"]
            for market in bookmaker.get("markets", []):
                market_key_str = market["key"]
                market_key_enum = self.MARKET_MAP.get(market_key_str)

                if not market_key_enum:
                    continue # Skip unknown markets

                if market_key_enum not in markets:
                    markets[market_key_enum] = Market(
                        market_key=market_key_enum,
                        period=Period.FULL_GAME # TOA basic odds are full game
                    )

                for outcome in market.get("outcomes", []):
                    price_american = outcome["price"]
                    outcome_price = OutcomePrice(
                        outcome_key=outcome["name"],
                        price_american=price_american,
                        price_decimal=american_to_decimal(price_american),
                        line=outcome.get("point"),
                        bookmaker_key=book_key,
                        last_update=datetime.fromisoformat(market["last_update"].replace("Z", "+00:00")),
                    )
                    markets[market_key_enum].outcomes.append(outcome_price)

        return EventOdds(event=event, markets=list(markets.values()))
