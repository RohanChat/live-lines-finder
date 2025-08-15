from __future__ import annotations
from typing import List, TYPE_CHECKING
from datetime import datetime, timedelta, UTC
import time

from src.feeds.base import OddsFeed
from src.feeds.query import FeedQuery
from src.feeds.models import SportKey, MarketKey, EventOdds
from src.analysis.base import AnalysisEngine

if TYPE_CHECKING:
    from src.chatbot.core import ChatbotCore


# Simple in-memory cache with a TTL
_cache = {}
CACHE_TTL_SECONDS = 60


def _format_odds_for_llm(all_event_odds: List[EventOdds]) -> str:
    """Formats a list of EventOdds into a compact string for an LLM prompt."""
    lines = []
    for event_odds in all_event_odds:
        event = event_odds.event
        home = next((c.name for c in event.competitors if c.role == "home"), "TBD")
        away = next((c.name for c in event.competitors if c.role == "away"), "TBD")
        lines.append(f"Event: {home} vs. {away} ({event.start_time.strftime('%Y-%m-%d %H:%M')})")

        for market in event_odds.markets:
            market_lines = []
            for outcome in market.outcomes:
                price_str = f"{outcome.price_american:+}" if outcome.price_american else "N/A"
                line_val_str = f" ({outcome.line})" if outcome.line is not None else ""
                bookmaker_str = f"@{outcome.bookmaker_key}" if outcome.bookmaker_key else ""
                market_lines.append(f"{outcome.outcome_key}{line_val_str} {price_str} {bookmaker_str}")
            lines.append(f"  Market: {market.market_key.value} -> {' | '.join(market_lines)}")
    return "\n".join(lines)


def get_best_bets(
    feed: OddsFeed,
    sport: SportKey,
    hours: int = 24,
    markets: List[MarketKey] | None = None,
    books: List[str] | None = None,
    top_k: int = 15, # Fetch more to give context to the LLM
    analysis_engines: List[AnalysisEngine] | None = None,
    chatbot: "ChatbotCore" | None = None,
) -> str:
    """
    Fetches odds, performs value analysis, and formats the best bets.
    """
    if markets is None:
        markets = [MarketKey.H2H, MarketKey.SPREAD, MarketKey.TOTAL]

    query = FeedQuery(
        sport=sport,
        markets=markets,
        bookmakers=books,
        start_time_to=datetime.now(UTC) + timedelta(hours=hours),
    )

    # Caching Logic (might need adjustment based on analysis complexity)
    cache_key = f"{sport.value}-{hours}-{','.join(m.value for m in markets)}"
    if cache_key in _cache:
        cached_data, timestamp = _cache[cache_key]
        if time.time() - timestamp < CACHE_TTL_SECONDS:
            print("[DEBUG] Returning cached result for get_best_bets.")
            return cached_data

    try:
        # Request deeplinks from the feed
        all_event_odds = feed.get_odds(query, include_deeplinks=True)
    except NotImplementedError:
        return f"Sorry, the configured odds provider ('{feed.__class__.__name__}') does not support fetching odds."
    except Exception as e:
        return f"Sorry, I couldn't fetch odds right now. Error: {e}"

    if not all_event_odds:
        return f"No upcoming events found for {sport.value} in the next {hours} hours."

    # --- Value Analysis ---
    # If a chatbot instance is provided, use the LLM for analysis.
    if chatbot:
        odds_summary = _format_odds_for_llm(all_event_odds[:top_k])
        prompt = (
            "You are a sports betting expert. Based on the following odds data, "
            f"please select the top 3-5 bets for {sport.value} that you believe have the highest value. "
            "For each, briefly explain your reasoning in a friendly and helpful tone. "
            "Present the information clearly using markdown. Here is the data:\n\n"
            f"{odds_summary}"
        )
        # Use a more direct method if available, but ask_question works.
        # We are not using function calling here, just direct Q&A.
        llm_response = chatbot.openai_client.chat.completions.create(
            model=chatbot.model,
            messages=[{"role": "user", "content": prompt}],
        ).choices[0].message.content

        # Cache and return the raw LLM response
        _cache[cache_key] = (llm_response, time.time())
        return llm_response

    # --- Fallback Formatting (if no analysis is performed) ---
    events_to_display = all_event_odds[:5] # Fallback to showing top 5
    lines = [f"Here are some of the top upcoming bets for *{sport.value}*:"]
    for event_odds in events_to_display:
        event = event_odds.event
        home = next((c.name for c in event.competitors if c.role == 'home'), 'TBD')
        away = next((c.name for c in event.competitors if c.role == 'away'), 'TBD')

        lines.append(f"\n--- *{home} vs. {away}* ---")
        lines.append(f"_{event.start_time.strftime('%Y-%m-%d %I:%M %p %Z')}_")

        for market in event_odds.markets:
            lines.append(f"\n  *{market.market_key.value.replace('_', ' ').title()}*")
            for outcome in market.outcomes:
                price_str = f"{outcome.price_american:+}" if outcome.price_american else "N/A"
                line_val_str = f" ({outcome.line})" if outcome.line is not None else ""
                bookmaker_str = f" at *{outcome.bookmaker_key}*" if outcome.bookmaker_key else ""

                outcome_line = f"    - {outcome.outcome_key}{line_val_str}: **{price_str}**{bookmaker_str}"
                lines.append(outcome_line)

                if outcome.link:
                    lines.append(f"      [Place Bet]({outcome.link})")

    if len(lines) <= 1:
        return "Found events, but no odds available for the selected markets."

    result_string = "\n".join(lines)
    _cache[cache_key] = (result_string, time.time())

    return result_string
