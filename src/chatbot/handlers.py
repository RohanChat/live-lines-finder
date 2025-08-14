from __future__ import annotations
from typing import List
from datetime import datetime, timedelta, UTC
import time

from src.feeds.base import OddsFeed
from src.feeds.query import FeedQuery
from src.feeds.models import SportKey, MarketKey

# Simple in-memory cache with a TTL
_cache = {}
CACHE_TTL_SECONDS = 60

def get_best_bets(
    feed: OddsFeed,
    sport: SportKey,
    hours: int = 24,
    markets: List[MarketKey] | None = None,
    books: List[str] | None = None,
    top_k: int = 3
) -> str:
    """
    Fetches odds and identifies the best bets based on some criteria.
    For this example, it will just format the first few available odds.
    """
    if markets is None:
        markets = [MarketKey.H2H, MarketKey.SPREAD, MarketKey.TOTAL]

    query = FeedQuery(
        sport=sport,
        markets=markets,
        bookmakers=books,
        start_time_to=datetime.now(UTC) + timedelta(hours=hours)
    )

    # Caching Logic
    cache_key = f"{sport.value}-{hours}-{','.join(m.value for m in markets)}"
    if cache_key in _cache:
        cached_data, timestamp = _cache[cache_key]
        if time.time() - timestamp < CACHE_TTL_SECONDS:
            return cached_data # Return formatted string from cache

    try:
        all_event_odds = feed.get_odds(query)
    except Exception as e:
        return f"Sorry, I couldn't fetch odds right now. Error: {e}"

    if not all_event_odds:
        return f"No upcoming events found for {sport.value} in the next {hours} hours."

    lines = []
    for event_odds in all_event_odds[:top_k]:
        event = event_odds.event
        home = next((c.name for c in event.competitors if c.role == 'home'), 'TBD')
        away = next((c.name for c in event.competitors if c.role == 'away'), 'TBD')
        lines.append(f"*{home} vs. {away}*")

        for market in event_odds.markets:
            line_str = f"  - {market.market_key.value}: "
            outcomes = []
            for outcome in market.outcomes:
                price_str = f"{outcome.price_american:+}" if outcome.price_american else ""
                line_val_str = f" ({outcome.line})" if outcome.line else ""
                outcomes.append(f"{outcome.outcome_key}{line_val_str} {price_str}")
            lines.append(line_str + " | ".join(outcomes))

    if not lines:
        return "Found events, but no odds available for the selected markets."

    result_string = "\n".join(lines)
    # Store the formatted result string in the cache
    _cache[cache_key] = (result_string, time.time())

    return result_string
