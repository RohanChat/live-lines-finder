from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime
from .models import SportKey, MarketKey, Period

@dataclass
class FeedQuery:
    sport: Optional[SportKey] = None
    leagues: Optional[List[str]] = None
    event_ids: Optional[List[str]] = None
    start_time_from: Optional[datetime] = None
    start_time_to: Optional[datetime] = None
    markets: Optional[List[MarketKey]] = None
    periods: Optional[List[Period]] = None
    bookmakers: Optional[List[str]] = None
    players: Optional[List[str]] = None
    teams: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    limit: Optional[int] = None
    extra: Dict = field(default_factory=dict)
