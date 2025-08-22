from __future__ import annotations
import json
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

class UnabatedApiAdapter(OddsFeed):
    """
    Clean Unabated REST API adapter using real API metadata.
    Routes: straight markets → /market/{league}/straight/odds
            player props → /market/{league}/props/odds
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or Config.UNABATED_API_KEY
        self.base_url = Config.UNABATED_DATA_API_URL

        if not self.api_key:
            raise ValueError("Unabated API key is not configured.")

        self.headers = {"X-Api-Key": self.api_key}

        # Load clean mappings from real API metadata
        self._load_mappings()
        
        # Load player mappings for name resolution
        self._load_player_mappings()
        
        # Market type routing
        self.market_routing = {
            MarketType.H2H: "straight",
            MarketType.SPREAD: "straight", 
            MarketType.TOTAL: "straight",
            MarketType.TEAM_TOTAL: "straight",
            MarketType.PLAYER_PROPS: "props"
        }

    def _load_mappings(self):
        """Load clean mappings from real API metadata"""
        try:
            with open('config/unabated_clean_mappings.json', 'r') as f:
                mappings = json.load(f)
                
            self.league_map = mappings["league_mappings"]
            self.sport_key_map = mappings["sport_key_mappings"] 
            self.sportsbooks_data = mappings["sportsbooks"]
            self.active_sportsbooks = mappings["active_sportsbooks_only"]
            self.bet_types_data = mappings["bet_types"]
            
        except FileNotFoundError:
            # Fallback to basic mappings if file not found
            self.league_map = {"nfl": "nfl", "nba": "nba", "mlb": "mlb", "nhl": "nhl", "wnba": "wnba"}
            self.sport_key_map = {"nfl": "americanfootball_nfl", "nba": "basketball_nba"}
            self.sportsbooks_data = {}
            self.active_sportsbooks = {}
            self.bet_types_data = {}

    def _load_player_mappings(self):
        """Load comprehensive player mappings for name resolution"""
        try:
            with open('config/comprehensive_mappings.json', 'r') as f:
                comprehensive_data = json.load(f)
                
            self.player_mappings = comprehensive_data.get('players', {})
            print(f"✅ Loaded player mappings for {len(self.player_mappings)} sports")
            
        except FileNotFoundError:
            print("⚠️  Player mappings not found, using Player_ID format")
            self.player_mappings = {}

    def _resolve_player_name(self, player_id: str, league: str) -> str:
        """Resolve player ID to actual name"""
        if league in self.player_mappings:
            player_data = self.player_mappings[league].get(str(player_id))
            if player_data and isinstance(player_data, dict):
                return player_data.get('name', f'Player_{player_id}')
        
        # Fallback to Player_ID format if not found
        return f'Player_{player_id}'

    def _make_request(self, endpoint: str, params: Dict[str, Any] | None = None) -> Any:
        """Make HTTP request to Unabated API"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API request failed for {endpoint}: {e}")
            raise

    def list_markets(self, sport: Optional[SportKey] = None) -> List[MarketType]:
        """Return supported market types"""
        return [MarketType.H2H, MarketType.SPREAD, MarketType.TOTAL, MarketType.TEAM_TOTAL, MarketType.PLAYER_PROPS]

    def list_sports(self) -> List[SportKey]:
        """Return sports based on league mappings"""
        sports = []
        for league, sport_key_str in self.sport_key_map.items():
            try:
                sports.append(SportKey(sport_key_str))
            except ValueError:
                continue
        return sports

    def list_bookmakers(self) -> List[Bookmaker]:
        """Get real bookmakers from API metadata"""
        bookmakers = []
        
        for sportsbook_id, name in self.active_sportsbooks.items():
            bookmakers.append(Bookmaker(
                key=f"sportsbook_{sportsbook_id}",
                title=name,
                source_id=sportsbook_id
            ))
        
        return sorted(bookmakers, key=lambda x: int(x.key.split('_')[1]))

    def get_events(self, q: FeedQuery) -> List[Event]:
        """Get events by delegating to get_odds"""
        event_odds_list = self.get_odds(q)
        return [eo.event for eo in event_odds_list]

    def get_odds(self, q: FeedQuery) -> List[EventOdds]:
        """
        Main entry point - routes markets to appropriate endpoints
        """
        if not q.leagues or not q.markets:
            return []

        results = []
        
        # Group markets by endpoint type
        straight_markets = [m for m in q.markets if self.market_routing.get(m) == "straight"]
        props_markets = [m for m in q.markets if self.market_routing.get(m) == "props"]
        
        # Fetch straight odds (h2h, spread, total)
        if straight_markets:
            results.extend(self._fetch_straight_odds(q, straight_markets))
        
        # Fetch props odds
        if props_markets:
            results.extend(self._fetch_props_odds(q))
        
        return results

    def get_event_odds(self, event_id: str, q: FeedQuery) -> EventOdds:
        """Get odds for specific event (not implemented for Unabated)"""
        raise NotImplementedError("Unabated API does not support fetching odds by event ID")

    def _normalize_event(self, raw) -> Event:
        """Normalize raw event data (not used in this implementation)"""
        raise NotImplementedError("This adapter uses direct parsing")

    def _normalize_event_odds(self, raw_event, raw_odds, q: FeedQuery) -> EventOdds:
        """Normalize raw event odds data (not used in this implementation)"""
        raise NotImplementedError("This adapter uses direct parsing")

    def _fetch_straight_odds(self, query: FeedQuery, markets: List[MarketType]) -> List[EventOdds]:
        """Fetch straight odds (h2h, spread, total) using /straight/odds endpoint"""
        results = []
        
        for league in query.leagues:
            unabated_league = self.league_map.get(league, league)
            
            try:
                endpoint = f"/market/{unabated_league}/straight/odds"
                response = self._make_request(endpoint)
                
                if response.get('success') and 'data' in response:
                    parsed_results = self._parse_straight_odds_response(
                        response['data'], league, markets
                    )
                    results.extend(parsed_results)
                    
            except Exception as e:
                print(f"Error fetching straight odds for {league}: {e}")
                
        return results

    def _fetch_props_odds(self, query: FeedQuery) -> List[EventOdds]:
        """Fetch player props using /props/odds endpoint"""
        results = []
        
        for league in query.leagues:
            unabated_league = self.league_map.get(league, league)
            
            try:
                endpoint = f"/market/{unabated_league}/props/odds"
                response = self._make_request(endpoint)
                
                if response.get('success') and 'data' in response:
                    parsed_results = self._parse_props_odds_response(
                        response['data'], league
                    )
                    results.extend(parsed_results)
                    
            except Exception as e:
                print(f"Error fetching props odds for {league}: {e}")
                
        return results

    def _parse_straight_odds_response(self, data: Dict[str, Any], league: str, markets: List[MarketType]) -> List[EventOdds]:
        """Parse straight odds response from API"""
        event_odds_list = []
        
        if not isinstance(data, dict) or 'odds' not in data:
            return event_odds_list
            
        odds_section = data['odds']
        unabated_league = self.league_map.get(league, league)
        
        if unabated_league not in odds_section:
            return event_odds_list
            
        sport_data = odds_section[unabated_league]
        period_types = sport_data.get('periodTypes', {})
        
        for period_name, period_data in period_types.items():
            for timing in ['pregame', 'live']:
                timing_data = period_data.get(timing, {})
                
                for event_key, event_data in timing_data.items():
                    if not isinstance(event_data, dict):
                        continue
                        
                    event_odds = self._build_event_odds_from_straight(
                        event_data, league, period_name, timing, markets
                    )
                    if event_odds:
                        event_odds_list.append(event_odds)
        
        return event_odds_list

    def _parse_props_odds_response(self, data: Dict[str, Any], league: str) -> List[EventOdds]:
        """Parse props odds response from API"""
        event_odds_list = []
        
        if not isinstance(data, dict) or 'odds' not in data:
            return event_odds_list
            
        odds_section = data['odds']
        unabated_league = self.league_map.get(league, league)
        
        if unabated_league not in odds_section:
            return event_odds_list
            
        sport_data = odds_section[unabated_league]
        period_types = sport_data.get('periodTypes', {})
        
        for period_name, period_data in period_types.items():
            for timing in ['pregame', 'live']:
                timing_data = period_data.get(timing, {})
                
                for event_key, event_data in timing_data.items():
                    if not isinstance(event_data, dict):
                        continue
                        
                    event_odds = self._build_event_odds_from_props(
                        event_data, league, period_name, timing
                    )
                    if event_odds:
                        event_odds_list.append(event_odds)
        
        return event_odds_list

    def _build_event_odds_from_straight(self, event_data: Dict[str, Any], league: str, 
                                      period_name: str, timing: str, markets: List[MarketType]) -> Optional[EventOdds]:
        """Build EventOdds from straight odds data"""
        try:
            event_id = str(event_data.get('eventId', ''))
            event_start = event_data.get('eventStart')
            event_name = event_data.get('eventName', '')
            
            # Create event
            event = Event(
                event_id=event_id,
                sport_key=self._league_to_sport_key(league),
                league=league,
                start_time=datetime.fromisoformat(event_start.replace('Z', '+00:00')) if event_start else datetime.now(),
                status="live" if timing == "live" else "upcoming",
                competitors=self._parse_competitors_from_name(event_name)
            )
            
            # Parse outcomes
            outcomes = self._parse_straight_outcomes(event_data, markets)
            
            # Create market
            market = Market(
                market_type=MarketType.H2H,  # Simplified - could be enhanced to detect actual type
                period=self._map_period(period_name),
                outcomes=outcomes
            )
            
            return EventOdds(event=event, markets=[market])
            
        except Exception as e:
            print(f"Error building straight event odds: {e}")
            return None

    def _build_event_odds_from_props(self, event_data: Dict[str, Any], league: str, 
                                   period_name: str, timing: str) -> Optional[EventOdds]:
        """Build EventOdds from props data"""
        try:
            event_id = str(event_data.get('eventId', ''))
            event_start = event_data.get('eventStart')
            event_name = event_data.get('eventName', '')
            
            # Create event
            event = Event(
                event_id=event_id,
                sport_key=self._league_to_sport_key(league),
                league=league,
                start_time=datetime.fromisoformat(event_start.replace('Z', '+00:00')) if event_start else datetime.now(),
                status="live" if timing == "live" else "upcoming",
                competitors=self._parse_competitors_from_name(event_name)
            )
            
            # Parse prop outcomes  
            outcomes = self._parse_props_outcomes(event_data, league)
            
            # Create market
            market = Market(
                market_type=MarketType.PLAYER_PROPS,
                period=self._map_period(period_name),
                scope="player",
                outcomes=outcomes
            )
            
            return EventOdds(event=event, markets=[market])
            
        except Exception as e:
            print(f"Error building props event odds: {e}")
            return None

    def _parse_competitors_from_name(self, event_name: str) -> List[Competitor]:
        """Parse team names from event name format"""
        competitors = []
        if ' @ ' in event_name:
            parts = event_name.split(' @ ')
            if len(parts) == 2:
                competitors = [
                    Competitor(name=parts[0].strip(), role="away", team_id=""),
                    Competitor(name=parts[1].strip(), role="home", team_id="")
                ]
        return competitors

    def _parse_straight_outcomes(self, event_data: Dict[str, Any], markets: List[MarketType]) -> List[OutcomePrice]:
        """Parse outcomes for straight markets"""
        outcomes = []
        sides_data = event_data.get('sides', {})
        
        for side_key, side_data in sides_data.items():
            if not isinstance(side_data, dict):
                continue
                
            side_index = side_data.get('sideIndex', 0)
            market_lines = side_data.get('marketSourceLines', {})
            
            for sportsbook_id, line_data in market_lines.items():
                if not isinstance(line_data, dict):
                    continue
                
                price = line_data.get('price')
                line_value = line_data.get('points')
                
                if price is None:
                    continue
                
                # Determine outcome key
                outcome_key = "away" if side_index == 0 else "home"
                sportsbook_name = self.active_sportsbooks.get(sportsbook_id, f'sportsbook_{sportsbook_id}')
                
                outcome = OutcomePrice(
                    outcome_key=outcome_key,
                    price_american=price,
                    line=line_value,
                    bookmaker_key=sportsbook_name
                )
                outcomes.append(outcome)
        
        return outcomes

    def _parse_props_outcomes(self, event_data: Dict[str, Any], league: str) -> List[OutcomePrice]:
        """Parse outcomes for player props with name resolution"""
        outcomes = []
        sides_data = event_data.get('sides', {})
        bet_type_id = event_data.get('betTypeId')
        
        # Get bet type name for context
        bet_type_name = self.bet_types_data.get(str(bet_type_id), {}).get('name', f'BetType_{bet_type_id}')
        
        for side_key, side_data in sides_data.items():
            if not isinstance(side_data, dict):
                continue
                
            side_index = side_data.get('sideIndex', 0)
            person_id = side_data.get('personId')
            market_lines = side_data.get('marketSourceLines', {})
            
            for sportsbook_id, line_data in market_lines.items():
                if not isinstance(line_data, dict):
                    continue
                
                price = line_data.get('price')
                line_value = line_data.get('points')
                
                if price is None:
                    continue
                
                # Build outcome key with bet type context and player name resolution
                outcome_type = "over" if side_index == 0 else "under"
                outcome_key = f"{bet_type_name} {outcome_type}"
                
                if person_id:
                    # Resolve player ID to actual name
                    player_name = self._resolve_player_name(person_id, league)
                    outcome_key = f"{player_name} {outcome_key}"
                
                # Resolve sportsbook name
                sportsbook_name = self.active_sportsbooks.get(sportsbook_id, f'sportsbook_{sportsbook_id}')
                
                outcome = OutcomePrice(
                    outcome_key=outcome_key,
                    price_american=price,
                    line=line_value,
                    bookmaker_key=sportsbook_name
                )
                outcomes.append(outcome)
        
        return outcomes

    def _map_period(self, period_name: str) -> Period:
        """Map period name to Period enum"""
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
        return period_map.get(period_name, Period.FULL_GAME)

    def _league_to_sport_key(self, league: str) -> SportKey:
        """Convert league to SportKey using mappings"""
        sport_key_str = self.sport_key_map.get(league, "americanfootball_nfl")
        try:
            return SportKey(sport_key_str)
        except ValueError:
            return SportKey.NFL