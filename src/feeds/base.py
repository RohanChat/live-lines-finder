from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, List, Dict, Any

from config import Config

class OddsFeed(ABC):
    """Interface for classes providing odds and event data."""

    def __init__(self):

        self.base_url = "https://api.the-odds-api.com/v4"

        self.api_key = Config.ODDS_API_KEY

        # Default sport configuration
        self.sport = "basketball_nba"
        self.odds_format = "american"

        # Default market configurations
        self.game_markets = ",".join([
            "h2h", "spreads", "totals"
        ])

        self.alt_markets = ",".join([
            "alternate_spreads", "alternate_totals",
            "team_totals", "alternate_team_totals"
        ])

        self.game_period_markets = ",".join([
            "h2h_q1", "h2h_q2", "h2h_q3", "h2h_q4", "h2h_h1", "h2h_h2", "h2h_3_way_q1",
            "h2h_3_way_q2", "h2h_3_way_q3", "h2h_3_way_q4", "h2h_3_way_h1", "h2h_3_way_h2",
            "spreads_q1", "spreads_q2", "spreads_q3", "spreads_q4", "spreads_h1", "spreads_h2",
            "alternate_spreads_q1", "alternate_spreads_q2", "alternate_spreads_q3", "alternate_spreads_q4",
            "alternate_spreads_h1", "alternate_spreads_h2", "totals_q1", "totals_q2", "totals_q3", "totals_q4",
            "totals_h1", "totals_h2", "alternate_totals_q1", "alternate_totals_q2", "alternate_totals_q3", 
            "alternate_totals_q4", "alternate_totals_h1", "alternate_totals_h2",
            "team_totals_q1", "team_totals_q2", "team_totals_q3", "team_totals_q4",
            "team_totals_h1", "team_totals_h2", "alternate_team_totals_q1", "alternate_team_totals_q2", 
            "alternate_team_totals_q3", "alternate_team_totals_q4",
            "alternate_team_totals_h1", "alternate_team_totals_h2"
        ])

        # List of all NBA player prop market keys
        self.player_prop_markets = ",".join([
            "player_points", "player_points_q1",
            "player_rebounds", "player_rebounds_q1",
            "player_assists", "player_assists_q1",
            "player_threes", "player_blocks", "player_steals",
            "player_blocks_steals", "player_turnovers",
            "player_points_rebounds_assists", "player_points_rebounds",
            "player_points_assists", "player_rebounds_assists",
            "player_field_goals", "player_frees_made", "player_frees_attempts",
            "player_first_basket", "player_first_team_basket",
            "player_double_double", "player_triple_double",
            "player_method_of_first_basket"
        ])

        self.player_alternate_markets = ",".join([
            "player_points_alternate", "player_assists_alternate",
            "player_rebounds_alternate", "player_blocks_alternate", "player_steals_alternate",
            "player_turnovers_alternate", "player_threes_alternate", "player_points_assists_alternate",
            "player_points_rebounds_alternate", "player_rebounds_assists_alternate",
            "player_points_rebounds_assists_alternate"
        ])

        self.player_all_markets = self.player_prop_markets + "," + self.player_alternate_markets

        self.markets = ",".join([
            self.game_markets, self.alt_markets,
            self.game_period_markets, self.player_all_markets
        ])

        # Default region configurations
        self.US = ",".join(["us", "us2"])
        self.UK = "uk"
        self.EU = "eu"
        self.AU = "au"
        self.all_regions = self.US + "," + self.UK + "," + self.EU + "," + self.AU

    @abstractmethod
    def get_todays_events(self, commence_time_from: str, commence_time_to: str) -> List[Dict[str, Any]]:
        """Return events scheduled between the provided times."""
        raise NotImplementedError

    @abstractmethod
    def get_events_between_hours(self, prev_hours: int = 6, next_hours: int = 24) -> List[Dict[str, Any]]:
        """Return events occurring between the hour range around now."""
        raise NotImplementedError

    @abstractmethod
    def get_events_in_next_hours(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Return events occurring within the next ``hours`` hours."""
        raise NotImplementedError

    @abstractmethod
    def get_props_for_todays_events(self, events: Iterable[Dict[str, Any]], markets: str, regions: str) -> List[Dict[str, Any]]:
        """Return prop odds for the given events."""
        raise NotImplementedError

    @abstractmethod
    def get_game_odds(self, markets: str, regions: str) -> List[Dict[str, Any]]:
        """Return game odds for the configured sport."""
        raise NotImplementedError

