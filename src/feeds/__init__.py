"""Data feed implementations for obtaining odds."""

from .base import OddsFeed
from .the_odds_api import TheOddsAPI
from .webhook import WebhookFeed
from .oddspapi_webhook import OddsPAPIWebhook

__all__ = ["OddsFeed", "TheOddsAPI", "WebhookFeed", "OddsPAPIWebhook"]
