from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from src.feeds.base import OddsFeed

class AnalysisEngine(ABC):
    """Abstract base class for modules that analyse odds data."""

    def __init__(self, feed: OddsFeed) -> None:
        self.feed = feed

    @abstractmethod
    def process_odds_for_event(self, event, *args, **kwargs):
        """Analyse odds data for the given event."""
        raise NotImplementedError
