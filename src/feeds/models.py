from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict
from datetime import datetime
import orjson
from pydantic import BaseModel, Field, ConfigDict, computed_field, field_serializer, model_validator
from ..utils.utils import _iso_utc_z

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


class Base(BaseModel):
    model_config = ConfigDict(
        use_enum_values=False,
        extra="forbid"
    )


class Bookmaker(Base):
    key: str
    title: Optional[str] = None
    source_id: Optional[str] = None


class Competitor(Base):
    name: str
    role: str  # "home" | "away" | "draw"
    team_id: Optional[str] = None


class OutcomePrice(Base):
    outcome_key: str           # "home"/"away"/"draw"/"over"/"under"/player name
    price_american: Optional[int] = None
    price_decimal: Optional[float] = None
    line: Optional[float] = None
    last_update: Optional[datetime] = None
    link: Optional[str] = None
    bookmaker_key: Optional[str] = None
    meta: Dict = Field(default_factory=dict)

    @field_serializer("last_update")
    def serialize_last_update(self, dt: Optional[datetime], _info):
        return _iso_utc_z(dt)


class Market(Base):
    market_type: MarketType
    sport: SportKey
    period: Period
    alternate: Optional[bool] = None
    scope: Optional[str] = None       # "game" | "team" | "player"
    subject_id: Optional[str] = None  # team_id or player_id
    outcomes: List[OutcomePrice] = Field(default_factory=list)
    meta: Dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_and_strip_computed_fields(cls, data):
        if isinstance(data, dict):
            d = dict(data)
            if "market_type" not in d and "market_key" in d:
                # let Pydantic coerce this string to MarketType
                d["market_type"] = d["market_key"]
            d.pop("market_key", None)  # remove output-only field for strict input
            return d
        return data

    @computed_field
    @property
    def market_key(self) -> str:
        mt = self.market_type
        return mt.value if isinstance(mt, Enum) else str(mt)


class Event(Base):
    event_id: str
    sport_key: SportKey
    league: Optional[str]
    start_time: datetime
    status: str
    competitors: List[Competitor]
    venue: Optional[str] = None
    meta: Dict = Field(default_factory=dict)

    @field_serializer("start_time")
    def serialize_start_time(self, dt: datetime, _info):
        return _iso_utc_z(dt)


class EventOdds(Base):
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


class FeedDelta(Base):
    type: DeltaType
    event_id: Optional[str]
    payload: Dict
    received_at: datetime

    @field_serializer("received_at")
    def serialize_received_at(self, dt: datetime, _info):
        return _iso_utc_z(dt)

# SGP

class SgpLeg(Base):
    event_id: str
    market_type: MarketType
    outcome_key: str
    line: Optional[float] = None
    period: Period = Period.FULL_GAME
    player_id: Optional[str] = None
    team_id: Optional[str] = None


class SgpQuoteRequest(Base):
    bookmaker: str
    legs: List[SgpLeg]
    stake: Optional[float] = None
    extra: Dict = Field(default_factory=dict)


class SgpQuoteResponse(Base):
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