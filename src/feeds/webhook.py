from __future__ import annotations

from typing import Callable, List, Dict, Any, Iterable

from .base import OddsFeed


class WebhookFeed(OddsFeed):
    """Stub implementation of :class:`OddsFeed` for webhook based providers."""

    def __init__(self) -> None:
        self._handlers: List[Callable[[Dict[str, Any]], None]] = []

    # Registration hooks -------------------------------------------------
    def register_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback to process incoming webhook payloads."""
        self._handlers.append(handler)

    def _notify(self, data: Dict[str, Any]) -> None:
        for handler in self._handlers:
            handler(data)

    # OddsFeed API -------------------------------------------------------
    def get_todays_events(self, commence_time_from: str, commence_time_to: str):
        raise NotImplementedError

    def get_events_between_hours(self, prev_hours: int = 6, next_hours: int = 24):
        raise NotImplementedError

    def get_events_in_next_hours(self, hours: int = 24):
        raise NotImplementedError

    def get_props_for_todays_events(self, events: Iterable[Dict[str, Any]], markets: str, regions: str):
        raise NotImplementedError

    def get_game_odds(self, markets: str, regions: str):
        raise NotImplementedError

