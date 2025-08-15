import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from src.chatbot.core import ChatbotCore
from src.feeds.models import SportKey, MarketKey, Event, EventOdds, Market, OutcomePrice, Competitor, SgpQuoteResponse
from src.utils.mappings import map_sport_name_to_key

@pytest.fixture
def mock_platform():
    return MagicMock()

@pytest.fixture
def mock_feed():
    mock = MagicMock()
    # Mock data for a WNBA game
    wnba_event = Event(
        event_id="wnba1",
        sport_key=SportKey.WNBA,
        league="WNBA",
        start_time=datetime.utcnow() + timedelta(hours=2),
        status="upcoming",
        competitors=[
            Competitor(name="Las Vegas Aces", role="home"),
            Competitor(name="New York Liberty", role="away")
        ]
    )
    wnba_market = Market(
        market_key=MarketKey.H2H,
        outcomes=[
            OutcomePrice(outcome_key="Las Vegas Aces", price_american=-200, bookmaker_key="draftkings", link="http://dk.com/bet1"),
            OutcomePrice(outcome_key="New York Liberty", price_american=180, bookmaker_key="draftkings", link="http://dk.com/bet2"),
        ]
    )
    mock.get_odds.return_value = [EventOdds(event=wnba_event, markets=[wnba_market])]
    return mock

@patch('src.chatbot.core.TheOddsApiAdapter')
def test_dynamic_sport_extraction(MockTheOddsApi, mock_platform, mock_feed):
    """
    Tests that asking for "WNBA" bets correctly calls get_best_bets with the WNBA SportKey.
    """
    # Arrange
    core = ChatbotCore(platform=mock_platform, openai_api_key="fake_key", product_id="test_prod")
    core.feed = mock_feed # Inject our mock feed

    # Mock the OpenAI response to simulate the LLM choosing the 'best_picks' function
    mock_openai_response = MagicMock()
    mock_choice = MagicMock()
    mock_message = MagicMock()
    mock_message.function_call.name = "best_picks"
    mock_message.function_call.arguments = '{"sport": "wnba"}'
    mock_choice.message = mock_message
    mock_openai_response.choices = [mock_choice]
    core.openai_client.chat.completions.create = MagicMock(return_value=mock_openai_response)

    # Act
    core.ask_question("suggest me some good wnba bets today")

    # Assert
    # Check that get_odds was called on the feed with the correct SportKey
    core.feed.get_odds.assert_called_once()
    query_arg = core.feed.get_odds.call_args[0][0]
    assert query_arg.sport == SportKey.WNBA

@patch('src.chatbot.core.TheOddsApiAdapter')
@patch('src.chatbot.core.UnabatedSgpAdapter')
def test_sgp_parlay_functionality(MockUnabatedSgp, MockTheOddsApi, mock_platform, mock_feed):
    """
    Tests that asking for an SGP correctly calls the SGP adapter.
    """
    # Arrange
    core = ChatbotCore(platform=mock_platform, openai_api_key="fake_key", product_id="test_prod")
    core.feed = mock_feed # Inject mock feed to find an event

    # Mock the SGP adapter's response
    mock_sgp_adapter_instance = MockUnabatedSgp.return_value
    mock_sgp_adapter_instance.deeplink_sgp.return_value = SgpQuoteResponse(
        bookmaker="draftkings",
        price_american=450,
        price_decimal=5.5,
        valid=True,
        deeplink_url="http://sgp-deeplink.com"
    )

    # Mock the OpenAI response for an SGP request
    mock_openai_response = MagicMock()
    mock_choice = MagicMock()
    mock_message = MagicMock()
    mock_message.function_call.name = "build_parlay"
    mock_message.function_call.arguments = '{"sport": "wnba", "legs": 2, "is_sgp": true}'
    mock_choice.message = mock_message
    mock_openai_response.choices = [mock_choice]
    core.openai_client.chat.completions.create = MagicMock(return_value=mock_openai_response)

    # Act
    result = core.ask_question("give me a 2-leg wnba sgp")

    # Assert
    assert "SGP suggestion" in result
    assert "http://sgp-deeplink.com" in result
    mock_sgp_adapter_instance.deeplink_sgp.assert_called_once()

def test_deeplink_in_fallback_output(mock_feed):
    """
    Tests that the fallback formatting in get_best_bets includes deeplinks.
    """
    # This test calls get_best_bets directly, bypassing the LLM analysis part
    # to test the formatting logic.
    from src.chatbot import handlers
    handlers._cache = {} # Clear cache before running this test

    result = handlers.get_best_bets(feed=mock_feed, sport=SportKey.WNBA)

    assert "[Place Bet](http://dk.com/bet1)" in result
    assert "[Place Bet](http://dk.com/bet2)" in result
