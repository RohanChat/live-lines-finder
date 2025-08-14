from __future__ import annotations
import asyncio
import json
import websockets
from typing import List, Dict, Any

from src.config import Config
from src.feeds.models import FeedDelta, DeltaType
from src.feeds.webhook.webhook import WebhookFeed, UpdateHandler

class BoltOddsWebhookAdapter(WebhookFeed):
    """
    Adapter for the BoltOdds WebSocket feed.
    """

    def __init__(self, api_key: str | None = None):
        super().__init__()
        token = api_key or Config.BOLTODDS_TOKEN
        if not token:
            raise ValueError("BoltOdds token is not configured.")
        self.wss_url = f"wss://spro.agency/api?key={token}"
        self.websocket = None

    async def _connect(self) -> None:
        """Establishes the WebSocket connection."""
        self.websocket = await websockets.connect(self.wss_url)

    async def _disconnect(self) -> None:
        """Closes the WebSocket connection."""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None

    async def _subscribe(self, q) -> None:
        """Sends a subscription message to the WebSocket."""
        # The query 'q' would be used here to build the filter payload.
        # For now, using a hardcoded example based on the old implementation.
        subscribe_message = {
            "action": "subscribe",
            "filters": {
                "sports": ["NBA", "MLB"],
                "sportsbooks": ["draftkings", "betmgm"],
                "markets": ["Moneyline", "Spread", "Total"]
            }
        }
        await self.websocket.send(json.dumps(subscribe_message))

    async def _incoming(self):
        """Async generator that yields messages from the WebSocket."""
        if not self.websocket:
            raise ConnectionError("WebSocket is not connected.")
        async for message in self.websocket:
            yield message

    def _parse_message(self, raw: str) -> List[FeedDelta]:
        """
        Parses a raw message from BoltOdds into a list of FeedDelta objects.
        This requires knowledge of the BoltOdds message structure.
        We'll assume a structure for this example.
        """
        data = json.loads(raw)
        deltas = []

        # Example: Check for a full snapshot message
        if data.get("type") == "snapshot" and "events" in data:
            for event_data in data["events"]:
                delta = FeedDelta(
                    type=DeltaType.SNAPSHOT,
                    event_id=event_data.get("id"),
                    payload=event_data,
                    received_at=None # This will be set by the base class
                )
                deltas.append(delta)
        
        # Example: Check for a single game update
        elif data.get("type") == "game_update" and "game" in data:
            game_data = data["game"]
            delta = FeedDelta(
                type=DeltaType.GAME_UPDATE,
                event_id=game_data.get("id"),
                payload=game_data,
                received_at=None
            )
            deltas.append(delta)

        # Example: Check for a single odds update
        elif data.get("type") == "odds_update" and "odds" in data:
            odds_data = data["odds"]
            delta = FeedDelta(
                type=DeltaType.PRICE_UPDATE,
                event_id=odds_data.get("event_id"),
                payload=odds_data,
                received_at=None
            )
            deltas.append(delta)

        return deltas