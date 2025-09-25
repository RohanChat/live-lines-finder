from __future__ import annotations
import logging
from typing import List, Optional, Tuple

from config.config import Config
from src.messaging.base import BaseMessagingClient
from src.chatbot.core import ChatbotCore
from src.feeds.base import OddsFeed
from src.feeds.api.unabated_api import UnabatedApiAdapter
from src.feeds.api.the_odds_api import TheOddsApiAdapter
from src.messaging.imessage.bot import iMessageBot
from src.messaging.mock_client.bot import MockMessagingClient
from src.feeds.webhook.boltodds_webhook import BoltOddsWebhookAdapter

logger = logging.getLogger(__name__)

def _default_feeds(cfg: Config) -> List[OddsFeed]:
    """
    Initializes and returns a list of default odds feed adapters.
    """
    feeds = []
    if cfg.ODDS_API_KEY:
        feeds.append(TheOddsApiAdapter(api_key=cfg.ODDS_API_KEY, mapping=cfg.TOA_MAPPING))
        logger.info("TheOddsApiAdapter initialized.")
    # Add other feed initializations here as needed
    # e.g., if cfg.UNABATED_API_KEY: feeds.append(...)
    return feeds

def _get_provider_names(cfg: Config) -> List[str]:
    """
    Extracts and returns the provider names from the list of feeds.
    """
    providers = cfg.ACTIVE_ODDS_PROVIDERS
    if isinstance(providers, str):
        return [p.strip() for p in providers.split(",")]
    return providers

def _select_model(cfg: Config, model: Optional[str]) -> str:
    """
    Selects the appropriate OpenAI model based on the runtime mode.
    """
    if model:
        return model
    else:
        return cfg.OPENAI_MODEL

def _build_platform_client(platform_name: str, cfg: Config):
    """
    Selects and returns the appropriate messaging client based on the platform name.
    For the web API, no client is needed.
    """
    pn = (platform_name or "mock").lower()
    if pn in ("imessage", "ios"):
        return iMessageBot()
    if pn in ("mock", "cli", "console"):
        return MockMessagingClient()
    if pn == "web":
        # The web API acts as its own client, so we don't need a separate bot instance.
        return None
    raise ValueError(f"Unsupported platform_name: {platform_name}")

def create_feed_adapter(name: str) -> OddsFeed:
    if name == "theoddsapi":
        return TheOddsApiAdapter()
    elif name == "boltodds":
        return BoltOddsWebhookAdapter()
    elif name == "unabated":
        return UnabatedApiAdapter()
    else:
        raise ValueError(f"Unknown odds provider: {name}")
    
def build_feeds(cfg: Config) -> List[OddsFeed]:
    """
    Builds and returns a list of OddsFeed adapters based on the configuration.
    """
    provider_names = _get_provider_names(cfg)
    feeds = [create_feed_adapter(name) for name in provider_names]
    return feeds

def create_chatbot(
    platform_name: str,
    mode: str = "test",
    provider_names: Optional[List[str]] = None,
    config: Optional[Config] = None,
) -> Tuple[ChatbotCore, BaseMessagingClient | None]:
    """
    Factory to assemble a ChatbotCore instance and its associated platform client.

    This function centralizes all wiring and configuration, ensuring that every
    runtime (CLI, web, workers) uses an identically configured chatbot.

    Returns:
        A tuple containing the configured ChatbotCore instance and the
        messaging client (or None for web/headless mode).
    """
    active_feeds: List[OddsFeed] = []
    cfg = config or Config()

    if provider_names:
        for name in provider_names:
            if name not in _get_provider_names(cfg):
                active_feeds.append(create_feed_adapter(name))

    config_feeds = build_feeds(cfg)
    if len(config_feeds) > 0:
        active_feeds = config_feeds
        logger.info(f"Initialized {len(config_feeds)} odds feed(s) from configuration.")
        
    else:
        active_feeds = _default_feeds(cfg)  
          
    if not active_feeds:
        raise RuntimeError("No odds feeds could be initialized. Check your API keys in the .env file.")

    model = _select_model(cfg, None)
    client = _build_platform_client(platform_name, cfg)

    product_config = cfg.PRODUCTS.get('betting_assistant', {}).get(mode, {})

    # --- FIX: Call ChatbotCore with the correct arguments ---
    bot = ChatbotCore(
        platform=client,
        feeds=active_feeds,
        model=model,
        product=product_config,
        openai_api_key=cfg.OPENAI_API_KEY,
    )
    
    logger.info(f"ChatbotCore created for platform '{platform_name}' in '{mode}' mode.")
    return bot, client