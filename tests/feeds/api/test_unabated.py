import pytest
import json
from unittest.mock import MagicMock

from src.feeds.api.unabated_api import UnabatedApiAdapter
from src.feeds.query import FeedQuery
from src.feeds.models import SportKey, Event

@pytest.fixture
def unabated_adapter():
    """Returns an instance of UnabatedApiAdapter with a dummy API key."""
    return UnabatedApiAdapter(api_key="dummy_key")

@pytest.fixture
def mock_requests_get(mocker):
    """Mocks requests.get to return a controlled response."""
    mock = mocker.patch("requests.get")
    mock.return_value = MagicMock()
    mock.return_value.status_code = 200
    return mock

def test_get_events(unabated_adapter, mock_requests_get):
    """
    Tests the get_events method for the Unabated adapter.
    """
    # Load the fixture data
    with open("tests/fixtures/unabated_upcoming.json", "r") as f:
        fixture_data = json.load(f)

    mock_requests_get.return_value.json.return_value = fixture_data

    query = FeedQuery(leagues=["nfl"])

    # Call the method under test
    events = unabated_adapter.get_events(query)

    # Assertions
    assert len(events) == 1

    event = events[0]
    assert isinstance(event, Event)
    assert event.event_id == "12345"
    assert event.sport_key == SportKey.NFL
    assert event.league == "nfl"

    assert len(event.competitors) == 2

    home_competitor = next((c for c in event.competitors if c.role == "home"), None)
    away_competitor = next((c for c in event.competitors if c.role == "away"), None)

    assert home_competitor is not None
    assert home_competitor.name == "Baltimore Ravens"
    assert home_competitor.team_id == "1"

    assert away_competitor is not None
    assert away_competitor.name == "Kansas City Chiefs"
    assert away_competitor.team_id == "2"

    # Verify that the correct URL was called
    mock_requests_get.assert_called_once_with(
        "https://api.unabated.com/v1/event/nfl/upcoming",
        params=None,
        headers={"Authorization": "Bearer dummy_key"}
    )

from src.feeds.api.unabated_sgp import UnabatedSgpAdapter
from src.feeds.models import SgpQuoteRequest, SgpLeg, MarketKey

@pytest.fixture
def unabated_sgp_adapter():
    """Returns an instance of UnabatedSgpAdapter with a dummy API key."""
    return UnabatedSgpAdapter(api_key="dummy_key")

def test_price_sgp(unabated_sgp_adapter, mock_requests_get):
    """Tests the price_sgp method."""
    with open("tests/fixtures/unabated_sgp_price.json", "r") as f:
        fixture_data = json.load(f)
    mock_requests_get.return_value.json.return_value = fixture_data

    request = SgpQuoteRequest(
        bookmaker="draftkings",
        legs=[SgpLeg(event_id="1", market_key=MarketKey.SPREAD, outcome_key="KC")],
    )

    response = unabated_sgp_adapter.price_sgp(request)

    assert response.valid is True
    assert response.price_american == 450
    assert response.price_decimal == 5.5
    assert response.bookmaker == "draftkings"
    mock_requests_get.assert_called_once()

def test_deeplink_sgp(unabated_sgp_adapter, mock_requests_get):
    """Tests the deeplink_sgp method."""
    with open("tests/fixtures/unabated_sgp_deeplink.json", "r") as f:
        fixture_data = json.load(f)
    mock_requests_get.return_value.json.return_value = fixture_data

    request = SgpQuoteRequest(
        bookmaker="draftkings",
        legs=[SgpLeg(event_id="1", market_key=MarketKey.SPREAD, outcome_key="KC")],
    )

    response = unabated_sgp_adapter.deeplink_sgp(request)

    assert response.valid is True
    assert response.deeplink_url is not None
    assert "draftkings.com" in response.deeplink_url
    mock_requests_get.assert_called_once()
