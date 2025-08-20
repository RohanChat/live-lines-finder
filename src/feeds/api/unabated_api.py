from __future__ import annotations
import json
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

from config.config import Config
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

        self.headers = {"X-Api-Key": self.api_key}  # Use X-Api-Key header, not Bearer token

        with open(maps_path, 'r') as f:
            self.maps = json.load(f)
        
        self.LEAGUE_MAP = self.maps.get("LEAGUE_MAP", {})
        self.SPORT_MAP = self.maps.get("SPORT_MAP", {}) 
        self.MARKET_MAP = self.maps.get("MARKET_TYPE_MAP", {})
        self.REVERSE_MARKET_MAP = self.maps.get("REVERSE_MARKET_MAP", {})
        self.BET_TYPE_TO_NAME = self.maps.get("BET_TYPE_TO_NAME", {})

    def _make_request(self, endpoint: str, params: Dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def list_sports(self) -> List[SportKey]:
        # Return sports based on available leagues in our mapping
        sports = []
        for league, sport_key in self.SPORT_MAP.items():
            try:
                sports.append(SportKey(sport_key))
            except ValueError:
                # If SportKey enum doesn't have this value, skip it
                continue
        return sports

    def list_bookmakers(self) -> List[Bookmaker]:
        # Unabated docs mention "marketSourceGroups" or "book" slugs.
        # A full implementation would fetch these from a dedicated endpoint if available,
        # or derive them from odds responses.
        return [
            Bookmaker(key="draftkings", title="DraftKings"),
            Bookmaker(key="fanduel", title="FanDuel"),
        ]

    def list_markets(self, sport: SportKey | None = None) -> List[MarketKey]:
        # Returns the markets we have mapped based on bet types
        markets = []
        for bet_type_id, market_key in self.MARKET_MAP.items():
            try:
                markets.append(MarketKey(market_key))
            except ValueError:
                # If MarketKey enum doesn't have this value, skip it
                continue
        return markets

    def get_events(self, q: FeedQuery) -> List[Event]:
        if not q.leagues:
            raise ValueError("A league must be specified for get_events with Unabated.")

        all_events = []
        for league in q.leagues:
            try:
                # Use the correct endpoint pattern: /event/{league}/upcoming
                raw_events = self._make_request(f"/event/{league}/upcoming")
                if isinstance(raw_events, dict) and 'data' in raw_events:
                    # Handle wrapped response format
                    events_data = raw_events['data']
                elif isinstance(raw_events, list):
                    events_data = raw_events
                else:
                    events_data = []
                
                for event_data in events_data:
                    try:
                        event = self._normalize_event(event_data, league)
                        all_events.append(event)
                    except Exception as e:
                        print(f"Error normalizing event: {e}")
                        continue
                        
            except Exception as e:
                print(f"Error fetching events for league {league}: {e}")
                continue
        
        return all_events

    def get_odds(self, q: FeedQuery) -> List[EventOdds]:
        # Unabated's snapshot endpoint: GET /market/{league}/{marketType}/odds
        if not q.leagues or not q.markets:
            raise ValueError("A league and at least one market must be specified.")

        all_event_odds = []
        
        for league in q.leagues:
            for market in q.markets:
                try:
                    # Convert MarketKey enum to bet type ID for Unabated
                    market_value = market.value if hasattr(market, 'value') else str(market)
                    bet_type_id = self.REVERSE_MARKET_MAP.get(market_value)
                    
                    if not bet_type_id:
                        print(f"No bet type mapping found for market: {market_value}")
                        continue
                    
                    # Use endpoint: /market/{league}/{marketType}/odds
                    # marketType can be 'straight' for game lines, 'props' for player props, 'futures' for outrights
                    market_type = "straight"  # Default to straight bets (game lines)
                    
                    endpoint = f"/market/{league}/{market_type}/odds"
                    raw_odds = self._make_request(endpoint)
                    
                    if isinstance(raw_odds, dict) and 'data' in raw_odds:
                        odds_data = raw_odds['data']
                    else:
                        odds_data = raw_odds
                    
                    # Parse the odds response and convert to EventOdds
                    event_odds_list = self._parse_odds_response(odds_data, league, bet_type_id, market)
                    all_event_odds.extend(event_odds_list)
                    
                except Exception as e:
                    print(f"Error fetching odds for league {league}, market {market}: {e}")
                    continue
        
        return all_event_odds

    def get_event_odds(self, event_id: str, q: FeedQuery) -> EventOdds:
        raise NotImplementedError("Unabated API does not support fetching odds by a single event ID in this manner.")

    def _normalize_event(self, raw: Dict[str, Any], league: str) -> Event:
        """
        Normalize Unabated event data to our Event format
        Unabated event structure: eventId, eventStart, eventTeams, name, etc.
        """
        competitors = []
        
        # Parse eventTeams - typically contains home/away team info
        event_teams = raw.get("eventTeams", [])
        
        for team in event_teams:
            # Determine role based on team data or position
            role = "home" if team.get("isHome", False) else "away"
            # Fallback: first team is away, second is home (common convention)
            if "isHome" not in team:
                role = "away" if len(competitors) == 0 else "home"
                
            competitors.append(Competitor(
                name=team.get("name", team.get("teamName", "Unknown")),
                role=role,
                team_id=str(team.get("teamId", team.get("id", "")))
            ))
        
        # If we don't have exactly 2 teams, try parsing from the event name
        if len(competitors) != 2:
            event_name = raw.get("name", "")
            # Parse team names from format like "Hawks Atlanta ATL @ Rockets Houston HOU"
            if " @ " in event_name:
                parts = event_name.split(" @ ")
                if len(parts) == 2:
                    competitors = [
                        Competitor(name=parts[0].strip(), role="away", team_id=""),
                        Competitor(name=parts[1].strip(), role="home", team_id="")
                    ]

        return Event(
            event_id=str(raw["eventId"]),
            sport_key=SportKey(self.SPORT_MAP.get(league, league)),
            league=league,
            start_time=datetime.fromisoformat(raw["eventStart"]),
            status="upcoming",  # TODO: Map statusId to status
            competitors=competitors,
        )

    def _normalize_event_odds(self, raw_event: Dict[str, Any], raw_odds: Dict[str, Any], q: FeedQuery) -> EventOdds:
        # This would parse the complex snapshot response from Unabated, which
        # contains lines from multiple bookmakers for a given market.
        # The structure is not provided in the prompt, so this is a placeholder.
        event = self._normalize_event(raw_event, q.leagues[0])
        return EventOdds(event=event, markets=[])

    def _parse_odds_response(self, odds_data: Dict[str, Any], league: str, bet_type_id: str, market: MarketKey) -> List[EventOdds]:
        """
        Parse Unabated odds response structure:
        odds -> {league} -> periodTypes -> {period} -> {pregame/live} -> {odds_key} -> odds data
        """
        event_odds_list = []
        
        try:
            # Navigate through the nested structure
            if 'odds' not in odds_data:
                print(f"No 'odds' key found in response")
                return event_odds_list
                
            odds_section = odds_data['odds']
            
            if league not in odds_section:
                print(f"No data for league '{league}' in odds response")
                return event_odds_list
                
            league_data = odds_section[league]
            
            if 'periodTypes' not in league_data:
                print(f"No 'periodTypes' found for league '{league}'")
                return event_odds_list
                
            period_types = league_data['periodTypes']
            
            # Iterate through periods (e.g., "game", "1sthalf")
            for period_name, period_data in period_types.items():
                if not isinstance(period_data, dict):
                    continue
                    
                # Iterate through timing (pregame/live)
                for timing, timing_data in period_data.items():
                    if timing not in ['pregame', 'live'] or not isinstance(timing_data, dict):
                        continue
                        
                    # Iterate through individual odds entries
                    for odds_key, odds_entry in timing_data.items():
                        if not isinstance(odds_entry, dict):
                            continue
                            
                        try:
                            # Extract event ID from the odds key (format: eid{eventId}:...)
                            if not odds_key.startswith('eid'):
                                continue
                            
                            # Check if this odds entry matches our requested bet type
                            entry_bet_type = odds_entry.get('betTypeId')
                            if str(entry_bet_type) != str(bet_type_id):
                                continue  # Skip odds entries that don't match our requested market
                                
                            # Parse event ID from odds key
                            event_id_str = odds_key.split(':')[0][3:]  # Remove 'eid' prefix
                            
                            event_odds = self._normalize_event_odds_from_unabated(
                                event_id_str, odds_entry, league, bet_type_id, market, period_name, timing
                            )
                            if event_odds:
                                event_odds_list.append(event_odds)
                        except Exception as e:
                            print(f"Error parsing event odds for key {odds_key}: {e}")
                            continue
                            
        except Exception as e:
            print(f"Error parsing odds response: {e}")
            
        print(f"Parsed {len(event_odds_list)} event odds entries")
        return event_odds_list

    def _normalize_event_odds_from_unabated(self, event_id: str, odds_entry: Dict[str, Any], 
                                           league: str, bet_type_id: str, market: MarketKey, 
                                           period_name: str, timing: str) -> Optional[EventOdds]:
        """
        Normalize Unabated event odds data to our EventOdds format
        """
        try:
            # Extract basic event info from the odds entry
            event_start = odds_entry.get('eventStart')
            event_name = odds_entry.get('eventName', '')
            
            # Parse competitors from event name (format: "Team A @ Team B")
            competitors = []
            if ' @ ' in event_name:
                parts = event_name.split(' @ ')
                if len(parts) == 2:
                    competitors = [
                        Competitor(name=parts[0].strip(), role="away", team_id=""),
                        Competitor(name=parts[1].strip(), role="home", team_id="")
                    ]
            
            # Create event object
            event = Event(
                event_id=event_id,
                sport_key=SportKey(self.SPORT_MAP.get(league, league)),
                league=league,
                start_time=datetime.fromisoformat(event_start) if event_start else datetime.now(),
                status="live" if timing == "live" else "upcoming",
                competitors=competitors
            )
            
            # Map period name to our Period enum
            period_map = {
                'game': Period.FULL_GAME,
                '1sthalf': Period.H1,
                '2ndhalf': Period.H2,
                '1stquarter': Period.Q1,
                '2ndquarter': Period.Q2,
                '3rdquarter': Period.Q3,
                '4thquarter': Period.Q4,
                'overtime': Period.OT,
            }
            period = period_map.get(period_name, Period.FULL_GAME)
            
            # Parse outcomes from sides (Unabated structure)
            outcomes = []
            sides_data = odds_entry.get('sides', {})
            
            for side_key, side_data in sides_data.items():
                if not isinstance(side_data, dict):
                    continue
                    
                # Get side index and team ID
                side_index = side_data.get('sideIndex')
                team_id = side_data.get('teamId')
                
                # Parse market source lines (sportsbooks)
                market_source_lines = side_data.get('marketSourceLines', {})
                
                for sportsbook_id, line_data in market_source_lines.items():
                    if not isinstance(line_data, dict):
                        continue
                    
                    # Extract price and other data
                    price = line_data.get('price')
                    
                    if price is not None:
                        # Determine outcome name based on side index
                        if side_index == 0:
                            outcome_name = "away"
                        elif side_index == 1:
                            outcome_name = "home"
                        else:
                            outcome_name = f"side_{side_index}"
                        
                        # Get sportsbook name from mapping if available
                        sportsbook_name = f"sportsbook_{sportsbook_id}"  # TODO: Map to actual name
                        
                        # Handle different market types
                        if market.value == 'h2h':  # Moneyline
                            outcomes.append(OutcomePrice(
                                outcome_key=outcome_name,
                                price_american=price,
                                bookmaker_key=sportsbook_name
                            ))
                        
                        elif market.value == 'spread':  # Point spread
                            # Unabated uses 'points' for spread lines
                            spread = line_data.get('points', line_data.get('line'))
                            if spread is not None:
                                outcomes.append(OutcomePrice(
                                    outcome_key=outcome_name,
                                    price_american=price,
                                    line=spread,
                                    bookmaker_key=sportsbook_name
                                ))
                            else:
                                print(f"Debug: No spread found in line_data: {line_data}")
                        
                        elif market.value == 'total':  # Over/Under
                            # Unabated uses 'points' for total lines
                            total = line_data.get('points', line_data.get('line'))
                            if total is not None:
                                # For totals, side index might indicate over/under
                                outcome_name = "over" if side_index == 0 else "under"
                                outcomes.append(OutcomePrice(
                                    outcome_key=outcome_name,
                                    price_american=price,
                                    line=total,
                                    bookmaker_key=sportsbook_name
                                ))
                            else:
                                print(f"Debug: No total found in line_data: {line_data}")
            
            # Create market
            market_data = Market(
                market_key=market,
                period=period,
                outcomes=outcomes
            )
            
            return EventOdds(event=event, markets=[market_data])
            
        except Exception as e:
            print(f"Error normalizing event odds for event {event_id}: {e}")
            return None
            
        except Exception as e:
            print(f"Error normalizing event odds: {e}")
            return None
