from __future__ import annotations
from src.feeds.models import SportKey

# A simple mapping from common names/synonyms to SportKey enums
# This can be expanded as needed.
SPORT_NAME_MAP = {
    "nfl": SportKey.NFL,
    "football": SportKey.NFL,
    "american football": SportKey.NFL,
    "ncaaf": SportKey.NCAAF,
    "college football": SportKey.NCAAF,
    "nba": SportKey.NBA,
    "basketball": SportKey.NBA,
    "wnba": SportKey.WNBA,
    "mlb": SportKey.MLB,
    "baseball": SportKey.MLB,
    "nhl": SportKey.NHL,
    "hockey": SportKey.NHL,
    "soccer": SportKey.FOOTBALL,
    "mls": SportKey.FOOTBALL, # Mapping MLS to generic football
}

def map_sport_name_to_key(sport_name: str) -> SportKey | None:
    """
    Maps a sport name string (e.g., 'nfl', 'WNBA') to a SportKey enum.
    Returns None if no mapping is found.
    """
    return SPORT_NAME_MAP.get(sport_name.lower())
