import pytest
from datetime import datetime
from src.feeds.models import (
    SportKey,
    MarketKey,
    Period,
    Event,
    Competitor,
    EventOdds,
    Market,
    OutcomePrice,
    SgpLeg,
    SgpQuoteRequest,
)

def test_event_odds_construction():
    """Tests that the main models can be constructed."""
    event = Event(
        event_id="test_event_123",
        sport_key=SportKey.NFL,
        league="NFL",
        start_time=datetime.utcnow(),
        status="upcoming",
        competitors=[
            Competitor(name="Team A", role="home"),
            Competitor(name="Team B", role="away"),
        ],
    )

    market = Market(
        market_key=MarketKey.H2H,
        outcomes=[
            OutcomePrice(outcome_key="home", price_american=110),
            OutcomePrice(outcome_key="away", price_american=-120),
        ],
    )

    event_odds = EventOdds(event=event, markets=[market])

    assert event_odds.event.event_id == "test_event_123"
    assert len(event_odds.markets) == 1
    assert event_odds.markets[0].market_key == MarketKey.H2H
    assert len(event_odds.markets[0].outcomes) == 2
    assert event_odds.markets[0].outcomes[0].price_american == 110

def test_sgp_leg_construction():
    """Tests that SGP models can be constructed."""
    leg1 = SgpLeg(
        event_id="test_event_123",
        market_key=MarketKey.SPREAD,
        outcome_key="home",
        line=-3.5,
        period=Period.FULL_GAME,
    )

    leg2 = SgpLeg(
        event_id="test_event_123",
        market_key=MarketKey.PLAYER_POINTS,
        outcome_key="player_1",
        line=25.5,
        player_id="player_1",
    )

    sgp_request = SgpQuoteRequest(
        bookmaker="test_bookie",
        legs=[leg1, leg2],
        stake=10.0,
    )

    assert sgp_request.bookmaker == "test_bookie"
    assert len(sgp_request.legs) == 2
    assert sgp_request.legs[0].market_key == MarketKey.SPREAD
    assert sgp_request.legs[1].player_id == "player_1"
    assert sgp_request.stake == 10.0
