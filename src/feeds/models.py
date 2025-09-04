from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict
from datetime import datetime

class SportKey(str, Enum):
    NFL = "americanfootball_nfl"
    NCAAF ="americanfootball_ncaa"
    NBA = "basketball_nba"
    NCAAB = "basketball_ncaa"
    WNBA = "basketball_wnba"
    MLB = "baseball_mlb"
    NHL = "icehockey_nhl"
    MMA = "mma"
    FOOTBALL = "football"
    BOXING = "boxing"
    TENNIS = "tennis"

class Period(str, Enum):
    FULL_GAME = "full_game"
    H1 = "1h"
    H2 = "2h"
    Q1 = "q1"
    Q2 = "q2"
    Q3 = "q3"
    Q4 = "q4"
    OT = "ot"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    INN1 = "inn1"
    INN3 = "inn3"
    INN5 = "inn5"
    INN7 = "inn7"

class MarketType(str, Enum):
    H2H = "h2h"
    SPREAD = "spread"
    TOTAL = "total"
    FUTURES = "futures"
    TEAM_TOTAL = "team_total"
    PLAYER_PROPS = "player_props"

@dataclass
class Bookmaker:
    key: str
    title: Optional[str] = None
    source_id: Optional[str] = None

@dataclass
class Competitor:
    name: str
    role: str  # "home" | "away" | "draw"
    team_id: Optional[str] = None

@dataclass
class OutcomePrice:
    outcome_key: str           # "home"/"away"/"draw"/"over"/"under"/player name
    price_american: Optional[int] = None
    price_decimal: Optional[float] = None
    line: Optional[float] = None
    last_update: Optional[datetime] = None
    link: Optional[str] = None
    bookmaker_key: Optional[str] = None
    meta: Dict = field(default_factory=dict)

@dataclass
class Market:
    market_type: MarketType
    sport: SportKey
    period: Period
    alternate: Optional[bool] = None
    scope: Optional[str] = None       # "game" | "team" | "player"
    subject_id: Optional[str] = None  # team_id or player_id
    outcomes: List[OutcomePrice] = field(default_factory=list)
    meta: Dict = field(default_factory=dict)
    
    # Backward compatibility property
    @property
    def market_key(self) -> str:
        return self.market_type.value

@dataclass
class Event:
    event_id: str
    sport_key: SportKey
    league: Optional[str]
    start_time: datetime
    status: str
    competitors: List[Competitor]
    venue: Optional[str] = None
    meta: Dict = field(default_factory=dict)

@dataclass
class EventOdds:
    event: Event
    markets: List[Market]

# streaming deltas
class DeltaType(str, Enum):
    SNAPSHOT = "snapshot"
    MARKET_UPDATE = "market_update"
    PRICE_UPDATE = "price_update"
    GAME_UPDATE = "game_update"
    GAME_REMOVED = "game_removed"
    BOOK_CLEAR = "book_clear"
    HEARTBEAT = "heartbeat"

@dataclass
class FeedDelta:
    type: DeltaType
    event_id: Optional[str]
    payload: Dict
    received_at: datetime

# SGP
@dataclass
class SgpLeg:
    event_id: str
    market_type: MarketType
    outcome_key: str
    line: Optional[float] = None
    period: Period = Period.FULL_GAME
    player_id: Optional[str] = None
    team_id: Optional[str] = None

@dataclass
class SgpQuoteRequest:
    bookmaker: str
    legs: List[SgpLeg]
    stake: Optional[float] = None
    extra: Dict = field(default_factory=dict)

@dataclass
class SgpQuoteResponse:
    bookmaker: str
    price_american: Optional[int]
    price_decimal: Optional[float]
    valid: bool
    deeplink_url: Optional[str] = None
    raw: Optional[Dict] = None

class Region(str, Enum):
    US = "us"
    UK = "uk"
    EU = "eu"
    AU = "au"
    OTHER = "other"