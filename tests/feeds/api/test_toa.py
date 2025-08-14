import pytest
import json
from unittest.mock import MagicMock

from src.feeds.api.the_odds_api import TheOddsApiAdapter
from src.feeds.query import FeedQuery
from src.feeds.models import SportKey, MarketKey, Event, EventOdds, OutcomePrice

@pytest.fixture
def toa_adapter():
    """Returns an instance of TheOddsApiAdapter with a dummy API key."""
    return TheOddsApiAdapter(api_key="dummy_key")

@pytest.fixture
def mock_requests_get(mocker):
    """Mocks requests.get to return a controlled response."""
    mock = mocker.patch("requests.get")
    mock.return_value = MagicMock()
    mock.return_value.status_code = 200

    # Load the fixture data
    with open("tests/fixtures/toa_odds_sample.json", "r") as f:
        fixture_data = json.load(f)

    mock.return_value.json.return_value = fixture_data
    return mock

def test_get_odds(toa_adapter, mock_requests_get):
    """
    Tests the get_odds method to ensure it correctly parses a sample response.
    """
    query = FeedQuery(sport=SportKey.NFL, markets=[MarketKey.H2H, MarketKey.SPREAD, MarketKey.TOTAL])

    # Call the method under test
    event_odds_list = toa_adapter.get_odds(query)

    # Assertions
    assert len(event_odds_list) == 1

    event_odds = event_odds_list[0]
    assert isinstance(event_odds, EventOdds)

    # Event assertions
    event = event_odds.event
    assert isinstance(event, Event)
    assert event.event_id == "f9a21b7941361949880e726d42a98f48"
    assert event.sport_key == SportKey.NFL
    assert event.competitors[0].name == "Denver Broncos"
    assert event.competitors[1].name == "Minnesota Vikings"

    # Market assertions
    assert len(event_odds.markets) == 3 # h2h, spreads, totals

    # H2H Market
    h2h_market = next((m for m in event_odds.markets if m.market_key == MarketKey.H2H), None)
    assert h2h_market is not None
    assert len(h2h_market.outcomes) == 2

    home_outcome = next((o for o in h2h_market.outcomes if o.outcome_key == "Denver Broncos"), None)
    assert home_outcome is not None
    assert isinstance(home_outcome, OutcomePrice)
    assert home_outcome.price_american == 220
    assert home_outcome.price_decimal == 3.20 # 1 + (220 / 100)
    assert home_outcome.bookmaker_key == "draftkings"

    # Spreads Market
    spread_market = next((m for m in event_odds.markets if m.market_key == MarketKey.SPREAD), None)
    assert spread_market is not None
    assert len(spread_market.outcomes) == 2

    vikings_spread = next((o for o in spread_market.outcomes if o.outcome_key == "Minnesota Vikings"), None)
    assert vikings_spread is not None
    assert vikings_spread.price_american == -110
    assert vikings_spread.line == -6.5

    # Totals Market
    total_market = next((m for m in event_odds.markets if m.market_key == MarketKey.TOTAL), None)
    assert total_market is not None
    assert len(total_market.outcomes) == 2

    over_outcome = next((o for o in total_market.outcomes if o.outcome_key == "Over"), None)
    assert over_outcome is not None
    assert over_outcome.price_american == -110
    assert over_outcome.line == 45.5

def test_list_sports(toa_adapter, mocker):
    """Tests the list_sports method."""
    mock_response = [
        {"key": "americanfootball_nfl", "group": "American Football", "title": "NFL", "description": "US Football"},
        {"key": "basketball_nba", "group": "Basketball", "title": "NBA", "description": "US Basketball"},
        {"key": "invalid_sport", "group": "Other", "title": "Invalid", "description": "An unsupported sport"}
    ]

    mock_get = mocker.patch("requests.get")
    mock_get.return_value.json.return_value = mock_response
    mock_get.return_value.status_code = 200

    sports = toa_adapter.list_sports()

    assert len(sports) == 2
    assert SportKey.NFL in sports
    assert SportKey.NBA in sports
    assert SportKey.NCAAF not in sports # Not in the mock response
