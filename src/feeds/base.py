from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional, Union

from src.utils.utils import redis_cache
from .models import Period, Region, SportKey, MarketType, Event, EventOdds, Bookmaker, Competitor, Market
from .query import FeedQuery

class OddsFeed(ABC):
    """Snapshot/REST-style interface."""

    @abstractmethod
    def provider_key(self, key: Union[SportKey, Period, MarketType, Market, Region]) -> str: ...

    # capabilities
    @abstractmethod
    def list_sports(self) -> List[SportKey]: ...
    @abstractmethod
    def list_bookmakers(self) -> List[Bookmaker]: ...
    @abstractmethod
    def list_markets(self, sport: Optional[SportKey] = None) -> List[MarketType]: ...

    @abstractmethod
    def get_events(self, q: FeedQuery) -> List[Event]: ...
    @redis_cache(prefix="feed:get_events", ttl=200)
    def get_events_cached(self, q: FeedQuery) -> List[Event]:
        events = self.get_events(q)
        return events

    @abstractmethod
    def get_event_odds(self, event: Event, q: FeedQuery) -> EventOdds: ...
    @redis_cache(prefix="feed:get_event_odds", ttl=200)
    def get_event_odds_cached(self, event: Event, q: FeedQuery) -> EventOdds:
        event_odds = self.get_event_odds(event, q)
        return event_odds

    @abstractmethod
    def get_odds(self, q: FeedQuery) -> List[EventOdds]: ...
    @redis_cache(prefix="feed:get_odds", ttl=200)
    def get_odds_cached(self, q: FeedQuery) -> List[EventOdds]:
        event_odds_list = self.get_odds(q)
        return event_odds_list

    @abstractmethod
    def _normalize_event(self, raw) -> Event: ...
    @abstractmethod
    def _normalize_event_odds(self, event: Event, raw_odds) -> EventOdds: ...

class SgpSupport:
    def supports_sgp(self) -> bool: return False
    def price_sgp(self, req): raise NotImplementedError
    def deeplink_sgp(self, req): raise NotImplementedError
