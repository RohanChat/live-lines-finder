from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional
from .models import SportKey, MarketKey, Event, EventOdds, Bookmaker
from .query import FeedQuery

class OddsFeed(ABC):
    """Snapshot/REST-style interface."""

    # capabilities
    @abstractmethod
    def list_sports(self) -> List[SportKey]: ...
    @abstractmethod
    def list_bookmakers(self) -> List[Bookmaker]: ...
    @abstractmethod
    def list_markets(self, sport: Optional[SportKey] = None) -> List[MarketKey]: ...

    # queries
    @abstractmethod
    def get_events(self, q: FeedQuery) -> List[Event]: ...
    @abstractmethod
    def get_event_odds(self, event_id: str, q: FeedQuery) -> EventOdds: ...
    @abstractmethod
    def get_odds(self, q: FeedQuery) -> List[EventOdds]: ...

    # mapping hooks
    @abstractmethod
    def _normalize_event(self, raw) -> Event: ...
    @abstractmethod
    def _normalize_event_odds(self, raw_event, raw_odds, q: FeedQuery) -> EventOdds: ...

class SgpSupport:
    def supports_sgp(self) -> bool: return False
    def price_sgp(self, req): raise NotImplementedError
    def deeplink_sgp(self, req): raise NotImplementedError
