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
from src.utils.odds_utils import american_to_decimal


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
                region_enum = Region(internal_region_str)  # match Enum name
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
    
    def internal_key(self, provider_key: str) -> Union[SportKey, Period, MarketType, Market, Region]:
        if provider_key in self._provider_to_internal_sport:
            return self._provider_to_internal_sport[provider_key]
        else: 
            raise NotImplementedError(f"internal_key not implemented for provider_key: {provider_key}")

    # ------------------------ HTTP ------------------------

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        q = {"apiKey": self.api_key, "dateFormat": "iso", "oddsFormat": "american", "includeLinks": "true", "includeBetLimits": "true"}
        if params:
            q.update({k: v for k, v in params.items() if v not in (None, "", [])})
        if "regions" not in q or not q.get("regions"):
            q["regions"] = self.provider_key(Region.US)  # default to US
        resp = requests.get(url, params=q, timeout=30)
        resp.raise_for_status()
        print("making api call \n")
        print(resp.url + "\n\n")
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
        
        print("Feedquery: \n")
        print(str(q) + "\n\n")

        events: List[Event] = []
        for sport in sports:
            params = {}
            if q.start_time_from:
                params["commenceTimeFrom"] = q.start_time_from.isoformat()
            if q.start_time_to:
                params["commenceTimeTo"] = q.start_time_to.isoformat()
            provider_key = self.provider_key(sport)
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

        if q.limit:
            print("Limiting events to: ", q.limit)
            events = events[: q.limit]

        print("Total events fetched: ", len(events), "\n\n")
        print(str(events) + "\n\n")
        return events

    def get_event_odds(self, event: Event, q: FeedQuery) -> EventOdds:
        
        if not event or not event.event_id:
            raise ValueError("Event with valid event_id must be provided.")

        print("Fetching odds for \n" + str(event) + "\n\n" "with feedquery:\n" + str(q) + "\n\n")
        sport_provider_key = self.provider_key(event.sport_key)
        markets_str = ""
        markets_strings = self.get_available_markets(event.sport_key, q.markets)
        for market in markets_strings:
            mkt_str = market
            markets_str += f"{mkt_str},"
        markets_str = markets_str.rstrip(",")  # Remove trailing comma
        if markets_str != "":
            raw = self._get(f"sports/{sport_provider_key}/events/{event.event_id}/odds", params={"markets": markets_str})
        else:
            raw = self._get(f"sports/{sport_provider_key}/events/{event.event_id}/odds")
        print("Raw odds data: \n"
              + str(raw) + "\n\n")
        normalised = self._normalize_event_odds(event=event, raw_odds=raw)
        print("Normalized odds data: \n"
              + str(normalised) + "\n\n")
        return normalised

    def get_odds(self, q: FeedQuery) -> List[EventOdds]:

        output_odds: List[EventOdds] = []

        ## get general odds for a given sport and/or market type. will not work for alternate or player props
        if q.event_ids:
            for i in range(len(q.event_ids)):
                event_id = q.event_ids[i]
                sport = q.sports[i] if q.sports and i < len(q.sports) else None
                if not sport:
                    raise ValueError("Sport must be provided in FeedQuery.sports when using event_ids.")
                event = Event(event_id=event_id, sport_key=sport)
                odds_for_event = self.get_event_odds(event, q)
                output_odds.append(odds_for_event)
        
        else:
            markets_str = ""
            if q.markets:
                for market in q.markets:
                    mkt_str = self.provider_key(market)
                    markets_str += f"{mkt_str},"
                markets_str = markets_str.rstrip(",")
            if q.sports:
                for sport in q.sports:
                    sport_key = self.provider_key(sport)
                    raw = self._get(f"sports/{sport_key}/odds", params={"markets": markets_str})

        print("RAW ODDS FETCHED FROM API")

        for event_data in raw:
                    # First normalize the event info
                    event = self._normalize_event(event_data)
                    
                    # Then normalize the odds for this event
                    event_odds = self._normalize_event_odds(event=event, raw_odds=event_data)
                    output_odds.append(event_odds)
        
        print("NORMALIZED ODDS: \n" + str(output_odds) + "\n\n")

        return output_odds

    def get_available_markets(self, sport_key: SportKey, market_types: Optional[List[MarketType]]) -> List[str]:
        """
        Get all available market keys for a sport, including period variants and player props.
        Returns provider market keys that can be used in API requests.
        """
        market_keys = []
        if not market_types or (MarketType.H2H in market_types or MarketType.SPREAD in market_types or MarketType.TOTAL in market_types or MarketType.TEAM_TOTAL in market_types):
            # Base markets with period variants
            market_keys.extend(self._get_base_markets_with_periods(sport_key))

        # additional_markets = self.mapping.get("additional_markets", {})
        # if sport_key == SportKey.FOOTBALL:
        #     market_keys.extend(additional_markets.get("global", []))

        # Sport-specific additional markets
        market_keys.extend(self._get_sport_specific_markets(sport_key))
        if not market_types or (MarketType.PLAYER_PROPS in market_types):
            # Player props
            market_keys.extend(self._get_player_props_markets(sport_key))

        return self._deduplicate_markets(market_keys)

    def _get_base_markets_with_periods(self, sport_key: SportKey) -> List[str]:
        """Get base markets (h2h, spreads, totals, team_totals) with sport-appropriate periods."""
        market_keys = []
        if sport_key == SportKey.MLB:
            base_markets = [MarketType.H2H, MarketType.SPREAD, MarketType.TOTAL]
        else:
            base_markets = [MarketType.H2H, MarketType.SPREAD, MarketType.TOTAL, MarketType.TEAM_TOTAL]
        valid_periods = self._get_valid_periods_for_sport(sport_key)
        
        for market_type in base_markets:
            try:
                base_key = self.provider_key(market_type)
                
                # Full game market
                market_keys.append(base_key)
                
                # Period variants
                for period in valid_periods:
                    try:
                        period_suffix = self.provider_key(period)
                        market_keys.append(f"{base_key}{period_suffix}")
                    except KeyError:
                        continue
                        
                # Alternate variants
                if market_type in [MarketType.SPREAD, MarketType.TOTAL, MarketType.TEAM_TOTAL]:
                    alt_base = f"alternate_{base_key}"
                    market_keys.append(alt_base)
                    
                    # Alternate period variants
                    for period in valid_periods:
                        try:
                            period_suffix = self.provider_key(period)
                            market_keys.append(f"{alt_base}{period_suffix}")
                        except KeyError:
                            continue
                            
            except KeyError:
                continue
                
        return market_keys

    def _get_valid_periods_for_sport(self, sport_key: SportKey) -> List[Period]:
        """Return periods that are valid for the given sport."""
        if sport_key in [SportKey.NFL, SportKey.NCAAF]:
            return [Period.H1, Period.H2, Period.Q1, Period.Q2, Period.Q3, Period.Q4]
        elif sport_key in [SportKey.NBA, SportKey.NCAAB, SportKey.WNBA]:
            return [Period.H1, Period.H2, Period.Q1, Period.Q2, Period.Q3, Period.Q4]
        elif sport_key == SportKey.NHL:
            return [Period.P1, Period.P2, Period.P3]
        elif sport_key == SportKey.MLB:
            return [Period.INN1, Period.INN3, Period.INN5, Period.INN7]
        elif sport_key == SportKey.FOOTBALL:  # Soccer
            return [Period.H1, Period.H2]
        else:
            # Default for other sports
            return [Period.H1, Period.H2]

    def _get_sport_specific_markets(self, sport_key: SportKey) -> List[str]:
        """Get markets that are specific to certain sports."""
        additional_markets = self.mapping.get("additional_markets", {})
        market_keys = []
        
        if sport_key == SportKey.FOOTBALL:  # Soccer
            # Soccer gets 3-way markets with periods
            valid_periods = self._get_valid_periods_for_sport(sport_key)
            market_keys.append("h2h_3_way")
            for period in valid_periods:
                try:
                    period_suffix = self.provider_key(period)
                    market_keys.append(f"h2h_3_way{period_suffix}")
                except KeyError:
                    continue
                    
        elif sport_key == SportKey.MLB:
            market_keys.extend(additional_markets.get("baseball_specific", []))
            
        elif sport_key == SportKey.NHL:
            market_keys.extend(additional_markets.get("hockey_specific", []))

        elif sport_key == SportKey.FOOTBALL:
            market_keys.extend(additional_markets.get("football_specific", []))
        
        return market_keys

    def _get_player_props_markets(self, sport_key: SportKey) -> List[str]:
        """Get all player props markets for the sport."""
        player_props = self.mapping.get("player_props", {}).get(sport_key.value, {})
        market_keys = []
        
        # Standard player props
        market_keys.extend(player_props.get("standard", []))
        
        # Alternate player props
        market_keys.extend(player_props.get("alternate", []))
        
        return market_keys

    def _deduplicate_markets(self, market_keys: List[str]) -> List[str]:
        """Remove duplicates while preserving order."""
        seen = set()
        deduplicated = []
        
        for key in market_keys:
            if key and key not in seen:
                seen.add(key)
                deduplicated.append(key)
                
        return deduplicated

                
    # ------------------------ Normalization ------------------------

    def _normalize_event(self, raw: Dict[str, Any]) -> Event:
        # Some endpoints return 'sport_key' as the provider key; map to internal enum if possible.

        print("receiving input: \n")
        print(str(raw) + "\n\n")

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

        output_event = Event(
            event_id=raw.get("id"),
            sport_key=internal_sport,
            league=None,  # provider encodes competition in sport_key
            start_time=start_dt,
            status=raw.get("completed", False) and "completed" or "upcoming",
            competitors=competitors,
            venue=None,
            meta={"provider_sport_key": raw_sport_key},
        )
        print("Constructed event output:\n")
        print(str(output_event) + "\n\n")
        return output_event


    def _normalize_event_odds(self, event: Event, raw_odds: Dict[str, Any]) -> EventOdds:

        print("Raw odds data: \n")
        print(str(raw_odds) + "\n")

        bookmakers = raw_odds.get("bookmakers", []) if raw_odds else []

        # Market bucket keyed by (market_type, period, scope, subject_id, provider_key)
        market_buckets: Dict[Tuple[MarketType, Period, str, Optional[str], str], Market] = {}

        home = None
        away = None
        for competitor in event.competitors:
            if competitor.role == "home":
                home = competitor.name
            elif competitor.role == "away":
                away = competitor.name

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

                mkt_type, scope = self.classify_market(provider_key)
                if mkt_type is None:
                    continue

                period = self.detect_period(provider_key)
                bucket_key = (mkt_type, period, scope, None, provider_key)
                if bucket_key not in market_buckets:
                    market_buckets[bucket_key] = Market(
                        sport=event.sport_key,
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
        print("Constructed EventOdds object:\n")
        print(str(EventOdds(event=event, markets=markets)) + "\n\n")
        return EventOdds(event=event, markets=markets)

    # ------------------------ Helpers ------------------------

    def detect_period(self, provider_market_key: str) -> Period:
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

    def classify_market(self, provider_market_key: str) -> Tuple[MarketType, str]:
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

    def _resolve_query_sports(self, q: FeedQuery) -> List[SportKey]:
        sports: List[SportKey] = []
        if q.sports:
            for s in q.sports:
                if isinstance(s, SportKey):
                    sports.append(s)
                else:
                    sports.append(SportKey(s))
        return sports

    def is_events_endpoint_valid(self, provider_market_key: str) -> bool:
        """
        Check if a provider market key is valid for the events endpoint.
        
        Returns True if the market key:
        - Contains 'player', 'batter', or 'pitcher' (player props)
        - Contains any period suffix from period_map (except full_game)
        - Is in the global additional_markets list
        
        Args:
            provider_market_key: The provider market key to check (e.g., "h2h_q1", "player_points")
            
        Returns:
            True if valid for events endpoint, False otherwise
        """
        # Check for player props keywords
        player_keywords = ["player", "batter", "pitcher"]
        if any(keyword in provider_market_key for keyword in player_keywords):
            return True
        
        # Check for period suffixes (excluding full_game which is empty string)
        period_suffixes = []
        for period_key, suffix in self.mapping.get("period_map", {}).items():
            if period_key != "full_game" and suffix:  # Skip full_game (empty string)
                period_suffixes.append(suffix)
        
        if any(suffix in provider_market_key for suffix in period_suffixes):
            return True
        
        # Check against global additional markets
        global_additional = self.mapping.get("additional_markets", {}).get("global", [])
        if provider_market_key in global_additional:
            return True
        
        return False

    def _compute_markets_params(self, internal_sport: SportKey, q: FeedQuery) -> List[str]:
        """
        Build list of provider market keys for this query.
        Returns all requested markets with proper period composition.
        """
        if q.markets:
            return self._get_explicit_markets(internal_sport, q)
        else:
            return self._get_all_markets(internal_sport, q)

    def _get_explicit_markets(self, internal_sport: SportKey, q: FeedQuery) -> List[str]:
        """Get markets for explicit market types requested in query."""
        market_keys = []
        
        for market_type in q.markets:
            if market_type == MarketType.PLAYER_PROPS:
                market_keys.extend(self._get_player_props_markets(internal_sport))
            else:
                market_keys.extend(self._get_base_market_variants(market_type, q.periods))
                
        # Add soccer-specific 3-way markets for H2H requests
        if MarketType.H2H in q.markets and internal_sport == SportKey.FOOTBALL:
            market_keys.extend(self._get_market_with_periods("h2h_3_way", q.periods))
            
        return self._deduplicate_markets(market_keys)

    def _get_all_markets(self, internal_sport: SportKey, q: FeedQuery) -> List[str]:
        """Get all available markets when no specific markets requested."""
        market_keys = []
        
        # Base markets
        base_markets = ["h2h", "spreads", "totals"]
        for base in base_markets:
            market_keys.extend(self._get_market_with_periods(base, q.periods))
            
        # Soccer-specific markets
        if internal_sport == SportKey.FOOTBALL:
            market_keys.extend(self._get_market_with_periods("h2h_3_way", q.periods))
            
        # Alternate and team total markets
        alternate_markets = ["alternate_spreads", "alternate_totals", "team_totals", "alternate_team_totals"]
        for alt_market in alternate_markets:
            market_keys.extend(self._get_market_with_periods(alt_market, q.periods))
            
        # Additional markets from mapping
        market_keys.extend(self._get_additional_markets(q.periods))
        
        # Player props
        market_keys.extend(self._get_player_props_markets(internal_sport))
        
        return self._deduplicate_markets(market_keys)

    def _get_base_market_variants(self, market_type: MarketType, periods: Optional[List[Period]]) -> List[str]:
        """Get base market and its variants (alternates, team totals)."""
        market_keys = []
        base_key = self.mapping.get("marketType_map", {}).get(market_type.value)
        
        if not base_key:
            return market_keys
            
        # Add base market with periods
        market_keys.extend(self._get_market_with_periods(base_key, periods))
        
        # Add related alternate markets
        if base_key == "spreads":
            market_keys.extend(self._get_market_with_periods("alternate_spreads", periods))
        elif base_key == "totals":
            market_keys.extend(self._get_market_with_periods("alternate_totals", periods))
        elif base_key == "team_totals":
            market_keys.extend(self._get_market_with_periods("team_totals", periods))
            market_keys.extend(self._get_market_with_periods("alternate_team_totals", periods))
            
        return market_keys

    def _get_market_with_periods(self, base_key: str, periods: Optional[List[Period]]) -> List[str]:
        """Generate market keys with period suffixes."""
        if not periods:
            return [base_key]
            
        market_keys = []
        for period in periods:
            suffix = self._get_period_suffix(period)
            market_keys.append(base_key + suffix)
            
        return market_keys

    def _get_period_suffix(self, period: Period) -> str:
        """Get period suffix for market composition."""
        period_map = self.mapping.get("period_map", {})
        suffix = period_map.get(period.value, "")
        return suffix if suffix else ""

    def _get_player_props_markets(self, internal_sport: SportKey) -> List[str]:
        """Get all player props markets for the sport."""
        player_props = self.mapping.get("player_props", {}).get(internal_sport.value, {})
        market_keys = []
        
        market_keys.extend(player_props.get("standard", []))
        market_keys.extend(player_props.get("alternate", []))
        
        return market_keys

    def _get_additional_markets(self, periods: Optional[List[Period]]) -> List[str]:
        """Get additional markets from mapping."""
        additional = self.mapping.get("additional_markets", {})
        market_keys = []
        
        # Global additional markets
        market_keys.extend(additional.get("global", []))
        
        # Period variants (only if no specific periods requested)
        if not periods:
            market_keys.extend(additional.get("period_variants", []))
            
        return market_keys

    def _deduplicate_markets(self, market_keys: List[str]) -> List[str]:
        """Remove duplicates while preserving order."""
        seen = set()
        deduplicated = []
        
        for key in market_keys:
            if key and key not in seen:
                seen.add(key)
                deduplicated.append(key)
                
        return deduplicated
