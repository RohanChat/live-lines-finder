import pytest
from src.feeds.base import OddsFeed, SgpSupport
from src.feeds.webhook.webhook import WebhookFeed

def test_odds_feed_is_abstract():
    """Verify that OddsFeed cannot be instantiated directly."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        class IncompleteOddsFeed(OddsFeed):
            pass
        IncompleteOddsFeed()

    with pytest.raises(TypeError, match="Can't instantiate abstract class .* without an implementation for abstract method"):
        class MissingMethods(OddsFeed):
            def list_sports(self): return []
            def list_bookmakers(self): return []
            def list_markets(self, sport=None): return []
            def get_events(self, q): return []
            def get_event_odds(self, event_id, q): return None
            # Missing get_odds, _normalize_event, _normalize_event_odds
        MissingMethods()

def test_sgp_support_interface():
    """Verify the default behavior of SgpSupport."""
    class MyFeed(SgpSupport):
        pass

    feed = MyFeed()
    assert not feed.supports_sgp()
    with pytest.raises(NotImplementedError):
        feed.price_sgp(None)
    with pytest.raises(NotImplementedError):
        feed.deeplink_sgp(None)

def test_webhook_feed_is_abstract():
    """Verify that WebhookFeed cannot be instantiated directly."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        class IncompleteWebhookFeed(WebhookFeed):
            pass
        IncompleteWebhookFeed()

    with pytest.raises(TypeError, match="Can't instantiate abstract class .* without an implementation for abstract method"):
        class MissingMethods(WebhookFeed):
            # Missing all abstract methods: _connect, _disconnect, _subscribe, _incoming, _parse_message
            pass
        MissingMethods()
