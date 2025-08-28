from __future__ import annotations
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Union

import requests

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
    Region
)
from src.feeds.query import FeedQuery


def american_to_decimal(american_odds: int) -> float:
    if american_odds is None:
        return None
    try:
        american_odds = int(american_odds)
    except Exception:
        return None
    if american_odds > 0:
        return round(1 + (american_odds / 100.0), 4)
    else:
        return round(1 - (100.0 / american_odds), 4)


class TheOddsApiAdapter(OddsFeed):
    """
    The Odds API adapter using your mapping JSON.
    - Uses the event odds endpoint for everything so that ALL market types are supported in one path.
    - Defaults to ALL markets and ALL bookmakers when not specified.
    """

    def __init__(self, api_key: Optional[str] = None, mapping: Optional[Dict[str, Any]] = None):

        self.api_key = api_key or Config.ODDS_API_KEY
        if not self.api_key:
            raise ValueError("TheOddsAPI API key is not configured.")

        # Base URL from Config, with safe default
        self.base_url = Config.ODDS_API_URL
        if not self.base_url:
            raise ValueError("TheOddsAPI base URL is not configured.")        

        self.mapping = mapping or Config.TOA_MAPPING

        # ---- REGIONS ----
        self._internal_to_provider_region: Dict[Region, str] = {}
        for internal_region_str, provider_val in self.mapping.get("regions", {}).items():
            try:
                region_enum = Region(internal_region_str.upper())  # match Enum name
            except Exception:
                continue
            # keep as raw string (comma-separated)
            self._internal_to_provider_region[region_enum] = str(provider_val).strip()
        
        # Special case: map Region.OTHER -> "all"
        if Region.OTHER not in self._internal_to_provider_region:
            if "all" in self.mapping.get("regions", {}):
                self._internal_to_provider_region[Region.OTHER] = str(
                    self.mapping["regions"]["all"]
                )


        # ---- SPORTS ----
        self._internal_to_provider_sport: Dict[SportKey, List[str]] = {}
        self._provider_to_internal_sport: Dict[str, SportKey] = {}
        for internal_sport_str, provider_keys in self.mapping.get("sports", {}).items():
            if internal_sport_str.startswith("_"):  # skip comments/unmodeled
                continue
            try:
                sk = SportKey(internal_sport_str)
            except Exception:
                continue
            keys_list = [str(k) for k in (provider_keys or [])]
            self._internal_to_provider_sport[sk] = keys_list
            for pk in keys_list:
                self._provider_to_internal_sport[pk] = sk

        # ---- PERIODS ----
        self._internal_to_provider_period: Dict[Period, str] = {}
        self._provider_to_internal_period: Dict[str, Period] = {}
        for internal_period_str, provider_suffix in self.mapping.get("period_map", {}).items():
            try:
                pd = Period(internal_period_str)
            except Exception:
                continue
            self._internal_to_provider_period[pd] = provider_suffix
            self._provider_to_internal_period[provider_suffix] = pd

        # ---- MARKET TYPES ----
        self._internal_to_provider_market_type: Dict[MarketType, str] = {}
        self._provider_to_internal_market_type: Dict[str, MarketType] = {}
        for internal_mt_str, provider_key in self.mapping.get("marketType_map", {}).items():
            if internal_mt_str.startswith("_"):
                continue
            try:
                mt = MarketType(internal_mt_str)
            except Exception:
                continue
            self._internal_to_provider_market_type[mt] = provider_key
            self._provider_to_internal_market_type[provider_key] = mt

    def provider_key(self, key: Union[SportKey, Period, MarketType, Market, Region]) -> str:
        if isinstance(key, SportKey):
            keys = self._internal_to_provider_sport.get(key, [])
            if not keys:
                raise KeyError(f"No provider keys mapped for SportKey={key}")
            return keys[0]  # canonical choice

        if isinstance(key, Period):
            suffix = self._internal_to_provider_period.get(key)
            if suffix is None:
                raise KeyError(f"No provider suffix mapped for Period={key}")
            return suffix

        if isinstance(key, MarketType):
            provider_key = self._internal_to_provider_market_type.get(key)
            if not provider_key:
                raise KeyError(f"No provider key mapped for MarketType={key}")
            return provider_key

        if isinstance(key, Market):
            base = self._internal_to_provider_market_type.get(key.market_type)
            if not base:
                raise KeyError(f"No provider key mapped for MarketType={key.market_type}")
            suffix = self._internal_to_provider_period.get(key.period, "")
            return f"{base}{suffix}"
        
        if isinstance(key, Region):
            provider_val = self._internal_to_provider_region.get(key)
            if not provider_val:
                raise KeyError(f"No provider region mapped for Region={key}")
            return provider_val

        raise TypeError(f"Unsupported type for provider_key: {type(key).__name__}")

    # ------------------------ HTTP ------------------------

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        q = {"apiKey": self.api_key, "dateFormat": "iso", "oddsFormat": "american"}
        if params:
            q.update({k: v for k, v in params.items() if v not in (None, "", [])})
        resp = requests.get(url, params=q, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ------------------------ Public API ------------------------

    def list_sports(self) -> List[SportKey]:
        """Return only sports present in your enum and mapping."""
        out: List[SportKey] = []
        for internal_sport_str in self.mapping.get("sports", {}).keys():
            try:
                out.append(SportKey(internal_sport_str))
            except Exception:
                pass
        return out

    def list_bookmakers(self) -> List[Bookmaker]:
        """
        No dedicated endpoint. We derive from a lightweight sample:
        - Find the first sport with any events, fetch one event's odds, collect bookmakers.
        """
        for sk in self.list_sports():
            provider_keys = self._internal_to_provider_sport_keys(sk)
            for psk in provider_keys:
                # get events
                events = self._get(f"sports/{psk}/events")
                if not events:
                    continue
                event_id = events[0]["id"]
                ev = self._get(f"sports/{psk}/events/{event_id}/odds", params={"markets": "h2h"})
                bks = []
                for b in ev.get("bookmakers", []):
                    bks.append(Bookmaker(key=b.get("key"), title=b.get("title")))
                if bks:
                    # unique by key
                    uniq = {}
                    for b in bks:
                        if b.key and b.key not in uniq:
                            uniq[b.key] = b
                    return list(uniq.values())
        return []

    def list_markets(self, sport: Optional[SportKey] = None) -> List[MarketType]:
        """
        Return all MarketType variants you support via mapping.
        (Your enum already includes H2H, SPREAD, TOTAL, TEAM_TOTAL, PLAYER_PROPS)
        """
        available: List[MarketType] = [MarketType.H2H, MarketType.SPREAD, MarketType.TOTAL, MarketType.TEAM_TOTAL]
        # add player props if sport supports any in mapping
        if sport:
            if self.mapping.get("player_props", {}).get(sport.value):
                available.append(MarketType.PLAYER_PROPS)
        else:
            # any sport has props?
            if any(self.mapping.get("player_props", {}).values()):
                available.append(MarketType.PLAYER_PROPS)
        # dedupe
        seen, out = set(), []
        for m in available:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    def get_events(self, q: FeedQuery) -> List[Event]:
        sports = self._resolve_query_sports(q)
        if not sports:
            raise ValueError("At least one sport must be provided in FeedQuery.sports")

        events: List[Event] = []
        for internal in sports:
            for provider_key in self._internal_to_provider_sport_keys(internal):
                params = {}
                if q.start_time_from:
                    params["commenceTimeFrom"] = q.start_time_from.isoformat()
                if q.start_time_to:
                    params["commenceTimeTo"] = q.start_time_to.isoformat()
                raw = self._get(f"sports/{provider_key}/events", params=params)
                for e in raw or []:
                    ev = self._normalize_event(e)
                    # optional team filter
                    if q.teams:
                        teams_lower = {t.lower() for t in q.teams}
                        names = {c.name.lower() for c in ev.competitors}
                        if not teams_lower & names:
                            continue
                    events.append(ev)

        # limit
        if q.limit:
            events = events[: q.limit]
        return events

    def get_event_odds(self, event_id: str, q: FeedQuery) -> EventOdds:
        return NotImplementedError("not implemented yet")

    def get_odds(self, q: FeedQuery) -> List[EventOdds]:
        
        output_odds = []

        requested_markets = q.markets or []
        for market in requested_markets:
            market_type = market.market_type
            if not (market_type == MarketType.ALTERNATE 
            or market_type == MarketType.PLAYER_PROPS):
                output_odds = output_odds + self.get_main_odds(market)
            else:
                return

                
    # ------------------------ Normalization ------------------------

    def _normalize_event(self, raw: Dict[str, Any]) -> Event:
        # Some endpoints return 'sport_key' as the provider key; map to internal enum if possible.
        raw_sport_key = raw.get("sport_key")
        internal_sport = None
        if raw_sport_key and raw_sport_key in self._provider_to_internal_sport:
            internal_sport = self._provider_to_internal_sport[raw_sport_key]
        # Fallback: try exact enum value
        if internal_sport is None and raw_sport_key:
            try:
                internal_sport = SportKey(raw_sport_key)
            except Exception:
                # leave None if unmapped; but our Event requires SportKey → choose best effort
                # If unmapped, raise to be explicit.
                pass
        if internal_sport is None:
            # Last resort: infer from teams if absolutely necessary (rare); else raise
            raise ValueError(f"Unrecognized sport_key from provider: {raw_sport_key}")

        competitors = [
            Competitor(name=raw.get("home_team"), role="home"),
            Competitor(name=raw.get("away_team"), role="away"),
        ]
        start_iso = raw.get("commence_time") or raw.get("commenceTime") or raw.get("start_time")
        start_dt = None
        if start_iso:
            start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))

        return Event(
            event_id=raw.get("id"),
            sport_key=internal_sport,
            league=None,  # provider encodes competition in sport_key
            start_time=start_dt,
            status=raw.get("completed", False) and "completed" or "upcoming",
            competitors=competitors,
            venue=None,
            meta={"provider_sport_key": raw_sport_key},
        )

    def _normalize_event_odds(self, raw_event: Dict[str, Any], raw_odds: Dict[str, Any], q: FeedQuery) -> EventOdds:
        event = self._normalize_event(raw_event if raw_event else raw_odds)
        bookmakers = raw_odds.get("bookmakers", []) if raw_odds else []

        # Market bucket keyed by (market_type, period, scope, subject_id, provider_key)
        market_buckets: Dict[Tuple[MarketType, Period, str, Optional[str], str], Market] = {}

        home = raw_event.get("home_team")
        away = raw_event.get("away_team")

        def detect_period(provider_market_key: str) -> Period:
            # Only map the ones present in your enum; put others in meta.
            if provider_market_key.endswith("_q1"):
                return Period.Q1
            if provider_market_key.endswith("_q2"):
                return Period.Q2
            if provider_market_key.endswith("_q3"):
                return Period.Q3
            if provider_market_key.endswith("_q4"):
                return Period.Q4
            if provider_market_key.endswith("_h1"):
                return Period.H1
            if provider_market_key.endswith("_h2"):
                return Period.H2
            if provider_market_key.endswith("_ot"):
                return Period.OT
            return Period.FULL_GAME

        def classify_market(provider_market_key: str) -> Tuple[MarketType, str]:
            k = provider_market_key
            if k.startswith("h2h"):
                return (MarketType.H2H, "game")
            if k.startswith("spreads") or k.startswith("alternate_spreads"):
                return (MarketType.SPREAD, "game")
            if k.startswith("totals") or k.startswith("alternate_totals"):
                return (MarketType.TOTAL, "game")
            if k.startswith("team_totals") or k.startswith("alternate_team_totals"):
                return (MarketType.TEAM_TOTAL, "team")
            # player props (NFL/NBA/MLB/NHL + aliases)
            if k.startswith("player_") or k.startswith("batter_") or k.startswith("pitcher_"):
                return (MarketType.PLAYER_PROPS, "player")
            # soccer extras
            if k in ("h2h_3_way",) or k.startswith("h2h_3_way_") or k in ("draw_no_bet", "double_chance"):
                return (MarketType.H2H, "game")
            if k == "btts":
                return (MarketType.TOTAL, "game")
            # default: skip unknowns cleanly
            return (None, "game")

        def normalize_outcome_name(mkt_type: MarketType, name: str, desc: Optional[str]) -> str:
            n = (name or "").strip().lower()
            d = (desc or "").strip()
            if mkt_type == MarketType.H2H:
                # Map to home/away/draw where possible
                if home and n == home.strip().lower():
                    return "home"
                if away and n == away.strip().lower():
                    return "away"
                if n in ("home", "away", "draw", "tie"):
                    return "draw" if n in ("draw", "tie") else n
                # Some books use team names; try fallback
                if home and n in home.strip().lower():
                    return "home"
                if away and n in away.strip().lower():
                    return "away"
                return n  # last resort
            if mkt_type in (MarketType.TOTAL, MarketType.TEAM_TOTAL, MarketType.PLAYER_PROPS):
                if n in ("over", "under", "yes", "no"):
                    return n
                # Some props invert (Over in description)
                if d and d.lower() in ("over", "under", "yes", "no"):
                    return d.lower()
            if mkt_type == MarketType.SPREAD:
                if n in ("home", "away"):
                    return n
                # Team names also appear
                if home and n == home.strip().lower():
                    return "home"
                if away and n == away.strip().lower():
                    return "away"
            return n

        for b in bookmakers:
            book_key = b.get("key")
            book_title = b.get("title")
            for m in b.get("markets", []):
                provider_key = m.get("key")
                if not provider_key:
                    continue

                mkt_type, scope = classify_market(provider_key)
                if mkt_type is None:
                    continue

                period = detect_period(provider_key)
                bucket_key = (mkt_type, period, scope, None, provider_key)
                if bucket_key not in market_buckets:
                    market_buckets[bucket_key] = Market(
                        market_type=mkt_type,
                        period=period,
                        scope=scope,
                        subject_id=None,
                        outcomes=[],
                        meta={"provider_key": provider_key, "bookmaker_count": 0},
                    )
                market_buckets[bucket_key].meta["bookmaker_count"] += 1

                last_update = m.get("last_update") or m.get("market_last_update")
                last_dt = None
                if last_update:
                    last_dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))

                for o in m.get("outcomes", []):
                    price = o.get("price")
                    point = o.get("point")
                    name = o.get("name")
                    desc = o.get("description")
                    link = o.get("link")
                    outcome_key = normalize_outcome_name(mkt_type, name, desc)

                    op = OutcomePrice(
                        outcome_key=outcome_key,
                        price_american=price if price is not None else None,
                        price_decimal=american_to_decimal(price) if price is not None else None,
                        line=point if point is not None else None,
                        last_update=last_dt,
                        link=link,
                        bookmaker_key=book_key,
                        meta={"bookmaker_title": book_title, "provider_market_key": provider_key}
                    )

                    # For player props, retain player name for filtering/SGP
                    if scope == "player":
                        # Provider puts player name in description (per your example)
                        if desc:
                            op.meta["player_name"] = desc

                    market_buckets[bucket_key].outcomes.append(op)

        markets = [m for m in market_buckets.values() if m.outcomes]
        return EventOdds(event=event, markets=markets)

    # ------------------------ Helpers ------------------------

    def _resolve_query_sports(self, q: FeedQuery) -> List[SportKey]:
        sports: List[SportKey] = []
        if q.sports:
            for s in q.sports:
                if isinstance(s, SportKey):
                    sports.append(s)
                else:
                    sports.append(SportKey(s))
        return sports

    def _compute_markets_param(self, internal_sport: SportKey, q: FeedQuery) -> str:
        """
        Build the comma-separated provider market keys for this query.
        When q.markets is None => include ALL:
          - base (h2h/spreads/totals)
          - soccer: h2h_3_way
          - team_totals + alternates
          - additional period variants
          - ALL player props (standard + alternate) supported for that sport
        If q.periods is provided, compose/limit to those period suffixes where applicable.
        """
        # Shortcuts into mapping
        m = self.mapping
        market_map = m.get("marketType_map", {})
        add = m.get("additional_markets", {}) or {}
        period_map = m.get("period_map", {}) or {}
        period_ext = period_map.get("_extended_recommended", {}) or {}

        def period_suffix(p: Period) -> str:
            key = p.value if hasattr(p, "value") else str(p)
            if key in period_map and isinstance(period_map[key], str):
                return period_map[key]
            if key in period_ext:
                return period_ext[key]
            return "" if p == Period.FULL_GAME else ""

        # Build set of required market keys
        market_keys: List[str] = []

        # Helper to add base + optional period suffix
        def add_base_with_periods(base_key: str):
            if q.periods:
                for p in q.periods:
                    suf = period_suffix(p)
                    market_keys.append(base_key + (suf or ""))
            else:
                market_keys.append(base_key)

        # 1) If explicit markets requested
        if q.markets:
            for mt in q.markets:
                mt_key = mt.value if hasattr(mt, "value") else str(mt)
                if mt == MarketType.PLAYER_PROPS:
                    pack = (m.get("player_props", {}) or {}).get(internal_sport.value)
                    if pack:
                        market_keys.extend(pack.get("standard", []) or [])
                        market_keys.extend(pack.get("alternate", []) or [])
                else:
                    base = market_map.get(mt_key)
                    if base:
                        add_base_with_periods(base)
                        # related alternates for spreads/totals/team_totals
                        if base == "spreads":
                            if q.periods:
                                for p in q.periods:
                                    suf = period_suffix(p)
                                    market_keys.append("alternate_spreads" + (suf or ""))
                            else:
                                market_keys.append("alternate_spreads")
                        if base == "totals":
                            if q.periods:
                                for p in q.periods:
                                    suf = period_suffix(p)
                                    market_keys.append("alternate_totals" + (suf or ""))
                            else:
                                market_keys.append("alternate_totals")
                        if base == "team_totals":
                            if q.periods:
                                for p in q.periods:
                                    suf = period_suffix(p)
                                    market_keys.append("team_totals" + (suf or ""))
                                    market_keys.append("alternate_team_totals" + (suf or ""))
                            else:
                                market_keys.extend(["team_totals", "alternate_team_totals"])
            # h2h_3_way if user explicitly asked H2H and sport supports it (mainly soccer)
            if MarketType.H2H in q.markets and internal_sport in [SportKey.FOOTBALL]:  # Only for soccer/football
                if q.periods:
                    for p in q.periods:
                        suf = period_suffix(p)
                        market_keys.append("h2h_3_way" + (suf or ""))
                else:
                    market_keys.append("h2h_3_way")

        # 2) No markets provided => include ALL
        else:
            # base
            for base in ("h2h", "spreads", "totals"):
                add_base_with_periods(base)
            # h2h 3-way (only for soccer/football)
            if internal_sport in [SportKey.FOOTBALL]:  # Only for soccer
                if q.periods:
                    for p in q.periods:
                        suf = period_suffix(p)
                        market_keys.append("h2h_3_way" + (suf or ""))
                else:
                    market_keys.append("h2h_3_way")
            # alternates + team totals + period variants (ALL)
            if q.periods:
                for p in q.periods:
                    suf = period_suffix(p)
                    market_keys.append("alternate_spreads" + (suf or ""))
                    market_keys.append("alternate_totals" + (suf or ""))
                    market_keys.append("team_totals" + (suf or ""))
                    market_keys.append("alternate_team_totals" + (suf or ""))
            else:
                market_keys.extend(["alternate_spreads", "alternate_totals", "team_totals", "alternate_team_totals"])
                # Include every period variant available
                market_keys.extend(add.get("period_variants", []) or [])
            # player props (standard + alternate) for this sport
            pack = (m.get("player_props", {}) or {}).get(internal_sport.value)
            if pack:
                market_keys.extend(pack.get("standard", []) or [])
                market_keys.extend(pack.get("alternate", []) or [])

            # Also include global additional markets (draw_no_bet, double_chance, btts, etc.)
            market_keys.extend(add.get("global", []) or [])

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for k in market_keys:
            if k and k not in seen:
                seen.add(k)
                deduped.append(k)
        return ",".join(deduped)
