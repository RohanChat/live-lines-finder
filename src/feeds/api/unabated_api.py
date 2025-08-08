import os
import requests
from typing import List, Dict, Any, Iterable

from config import Config
from feeds.base import OddsFeed

class UnabatedAPI(OddsFeed):
    """
    Implementation of OddsFeed using the Unabated REST API for point-in-time data.
    """

    def __init__(self):
        super().__init__()
        self.api_key = Config.UNABATED_API_KEY
        self.base_url = Config.UNABATED_DATA_API_URL
        if not self.api_key or not self.base_url:
            raise ValueError("Unabated API key or URL not found in environment variables.")
        self.headers = {"X-API-Key": self.api_key}

    def _make_request(self, endpoint: str) -> Dict[str, Any]:
        """Helper method to make requests to the Unabated API."""
        url = f"{self.base_url}{endpoint}"
        print(f"Fetching data from {url}...")
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 200:
            print(f"Successfully fetched data from {endpoint}.")
            return response.json()
        else:
            print(f"Error fetching {endpoint}: {response.status_code} - {response.text}")
            response.raise_for_status()

    def get_bet_types(self) -> List[Dict[str, Any]]:
        """
        Fetches a list of all available bet types from the Unabated API.
        """
        return self._make_request("/bettype")

    def get_upcoming_events(self, league: str) -> List[Dict[str, Any]]:
        """
        Fetches upcoming events for a specific league.
        """
        return self._make_request(f"/event/{league}/upcoming")

    # --- Abstract Method Implementations ---

    def get_todays_events(self, commence_time_from: str, commence_time_to: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("This method is not yet implemented for UnabatedAPI.")

    def get_events_between_hours(self, prev_hours: int = 6, next_hours: int = 24) -> List[Dict[str, Any]]:
        raise NotImplementedError("This method is not yet implemented for UnabatedAPI.")

    def get_events_in_next_hours(self, hours: int = 24) -> List[Dict[str, Any]]:
        raise NotImplementedError("This method is not yet implemented for UnabatedAPI.")

    def get_props_for_todays_events(self, events: Iterable[Dict[str, Any]], markets: str, regions: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("This method is not yet implemented for UnabatedAPI.")

    def get_game_odds(self, markets: str, regions: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("This method is not yet implemented for UnabatedAPI.")
