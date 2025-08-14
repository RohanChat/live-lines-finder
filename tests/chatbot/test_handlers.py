import pytest
from unittest.mock import MagicMock
from datetime import datetime

from src.chatbot.handlers import get_best_bets
from src.feeds.models import SportKey, MarketKey, Event, EventOdds, Market, OutcomePrice, Competitor

def test_get_best_bets_handler():
    """
    Tests the get_best_bets handler with a mock feed.
    """
    # 1. Create mock EventOdds data
    mock_event = Event(
        event_id="test1",
        sport_key=SportKey.NBA,
        league="NBA",
        start_time=datetime.utcnow(),
        status="upcoming",
        competitors=[
            Competitor(name="Lakers", role="home"),
            Competitor(name="Clippers", role="away")
        ]
    )
    mock_market = Market(
        market_key=MarketKey.H2H,
        outcomes=[
            OutcomePrice(outcome_key="Lakers", price_american=-150),
            OutcomePrice(outcome_key="Clippers", price_american=130),
        ]
    )
    mock_event_odds = EventOdds(event=mock_event, markets=[mock_market])

    # 2. Create a mock feed object
    mock_feed = MagicMock()
    mock_feed.get_odds.return_value = [mock_event_odds]

    # 3. Call the handler
    result = get_best_bets(feed=mock_feed, sport=SportKey.NBA)

    # 4. Assert the output is formatted correctly
    assert "*Lakers vs. Clippers*" in result
    # Note: The format string `:+` does not add parentheses, so we match the actual output.
    assert "h2h: Lakers -150 | Clippers +130" in result

    # 5. Assert the mock was called correctly
    mock_feed.get_odds.assert_called_once()
    query_arg = mock_feed.get_odds.call_args.args[0]
    assert query_arg.sport == SportKey.NBA
    assert query_arg.markets == [MarketKey.H2H, MarketKey.SPREAD, MarketKey.TOTAL]

def test_get_best_bets_caching(mocker):
    """
    Tests that the handler correctly caches results.
    """
    # We need to clear the cache before this test runs
    from src.chatbot import handlers
    handlers._cache = {}

    mock_feed = MagicMock()
    mock_feed.get_odds.return_value = [
        EventOdds(
            event=Event("t1", SportKey.NBA, "NBA", datetime.utcnow(), "upcoming", []),
            markets=[]
        )
    ]

    # Call the handler twice with the same arguments
    get_best_bets(feed=mock_feed, sport=SportKey.NBA)
    get_best_bets(feed=mock_feed, sport=SportKey.NBA)

    # Assert that the expensive feed method was only called ONCE
    mock_feed.get_odds.assert_called_once()
