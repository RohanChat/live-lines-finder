import pytest
import json
from unittest.mock import MagicMock

from src.feeds.api.oddspapi_api import OddsPapiApiAdapter
from src.feeds.query import FeedQuery
from src.feeds.models import Event

@pytest.fixture
def oddspapi_adapter():
    """Returns an instance of OddsPapiApiAdapter with a dummy API key."""
    return OddsPapiApiAdapter(api_key="dummy_key")

@pytest.fixture
def mock_requests_get(mocker):
    """Mocks requests.get to return a controlled response."""
    mock = mocker.patch("requests.get")
    mock.return_value = MagicMock()
    mock.return_value.status_code = 200
    return mock

def test_list_sports(oddspapi_adapter, mock_requests_get):
    """Tests the list_sports method."""
    with open("tests/fixtures/oddspapi_sports.json", "r") as f:
        fixture_data = json.load(f)
    mock_requests_get.return_value.json.return_value = fixture_data

    sports = oddspapi_adapter.list_sports()

    assert len(sports) == 3
    assert sports[1]["sportName"] == "American Football"
    mock_requests_get.assert_called_once_with(
        "https://api-v2.oddspapi.io/api/v2/sports",
        params={"API-Key": "dummy_key"}
    )

def test_get_events(oddspapi_adapter, mock_requests_get):
    """Tests the get_events method."""
    with open("tests/fixtures/oddspapi_fixtures.json", "r") as f:
        fixture_data = json.load(f)
    mock_requests_get.return_value.json.return_value = fixture_data

    events = oddspapi_adapter.get_events(FeedQuery())

    assert len(events) == 2

    event1 = events[0]
    assert isinstance(event1, Event)
    assert event1.event_id == "nfl_2023_g1"
    assert event1.league == "NFL"
    assert event1.competitors[0].name == "Kansas City Chiefs"

    mock_requests_get.assert_called_once_with(
        "https://api-v2.oddspapi.io/api/v2/fixtures",
        params={"API-Key": "dummy_key"}
    )
