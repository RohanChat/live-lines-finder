from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional, Union
from .models import Period, Region, SportKey, MarketType, Event, EventOdds, Bookmaker, Competitor, Market
from .query import FeedQuery

class OddsFeed(ABC):
    """Snapshot/REST-style interface."""

    # capabilities
    @abstractmethod
    def list_sports(self) -> List[SportKey]: ...
    @abstractmethod
    def list_bookmakers(self) -> List[Bookmaker]: ...
    @abstractmethod
    def list_markets(self, sport: Optional[SportKey] = None) -> List[MarketType]: ...
    @abstractmethod
    def get_events(self, q: FeedQuery) -> List[Event]: ...

    @abstractmethod
    def get_event_odds(self, event: Event, q: FeedQuery) -> EventOdds: ...
    @abstractmethod
    def get_odds(self, q: FeedQuery) -> List[EventOdds]: ...

    @abstractmethod
    def _normalize_event(self, raw) -> Event: ...
    @abstractmethod
    def _normalize_event_odds(self, raw_event, raw_odds, q: FeedQuery) -> EventOdds: ...

    @abstractmethod
    def provider_key(self, key: Union[SportKey, Period, MarketType, Market, Region]) -> str: ...

class SgpSupport:
    def supports_sgp(self) -> bool: return False
    def price_sgp(self, req): raise NotImplementedError
    def deeplink_sgp(self, req): raise NotImplementedError
