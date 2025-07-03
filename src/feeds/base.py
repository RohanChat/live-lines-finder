from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, List, Dict, Any

class OddsFeed(ABC):
    """Interface for classes providing odds and event data."""

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

