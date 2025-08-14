from __future__ import annotations
import asyncio
import json
import websockets
import base64
import uuid
from typing import List, Dict, Any

from config.config import Config
from src.feeds.models import FeedDelta, DeltaType
from src.feeds.webhook.webhook import WebhookFeed

# Based on the original unabated_webhook.py file
SUBSCRIPTION_QUERY = """
    subscription marketLineUpdate {
      marketLineUpdate {
        leagueId
        marketSourceGroup
        marketLines {
          marketId
          marketLineId
          price
          statusId
        }
      }
    }
"""

class UnabatedWsAdapter(WebhookFeed):
    """
    Adapter for the Unabated GraphQL WebSocket feed, using manual protocol implementation.
    """

    def __init__(self, api_key: str | None = None, host: str | None = None):
        super().__init__()
        self.host = host or Config.UNABATED_REALTIME_API_HOST
        self.api_key = api_key or Config.UNABATED_API_KEY
        
        if not self.host or not self.api_key:
            raise ValueError("Unabated real-time host or API key is not configured.")

        # Construct the special WebSocket URL required by AWS AppSync
        endpoint = f"wss://{self.host}/graphql/realtime"
        header = base64.b64encode(json.dumps({"host": self.host, "Authorization": self.api_key}).encode()).decode()
        payload = base64.b64encode(b"{}").decode()
        self.wss_url = f"{endpoint}?header={header}&payload={payload}"
        self.websocket = None
        self.subscription_id = str(uuid.uuid4())

    async def _connect(self) -> None:
        """Establishes the WebSocket connection."""
        self.websocket = await websockets.connect(self.wss_url, subprotocols=['graphql-ws'])
        # 1. Send connection_init
        await self.websocket.send(json.dumps({
            "type": "connection_init",
            "payload": {"authorization": {"host": self.host, "Authorization": self.api_key}}
        }))

    async def _disconnect(self) -> None:
        """Closes the WebSocket connection."""
        if self.websocket:
            await self.websocket.close()

    async def _subscribe(self, q) -> None:
        """Waits for ack and sends the subscription query."""
        # 2. Wait for ack
        while True:
            message = await self.websocket.recv()
            if json.loads(message).get("type") == "connection_ack":
                break

        # 3. Send start message
        start_payload = {
            "id": self.subscription_id,
            "type": "start",
            "payload": {
                "data": json.dumps({"query": SUBSCRIPTION_QUERY}), # Query could be built from q
                "extensions": {
                    "authorization": {"host": self.host, "Authorization": self.api_key}
                }
            }
        }
        await self.websocket.send(json.dumps(start_payload))

    async def _incoming(self):
        """Async generator that yields data messages from the WebSocket."""
        if not self.websocket:
            raise ConnectionError("WebSocket is not connected.")

        async for message in self.websocket:
            parsed = json.loads(message)
            if parsed.get("type") == "data":
                yield parsed

    def _parse_message(self, raw: Dict[str, Any]) -> List[FeedDelta]:
        """Parses a raw 'data' message into FeedDelta objects."""
        deltas = []
        market_line_update = raw.get("payload", {}).get("data", {}).get("marketLineUpdate")

        if market_line_update:
            delta = FeedDelta(
                type=DeltaType.MARKET_UPDATE,
                event_id=None,
                payload=market_line_update,
                received_at=None
            )
            deltas.append(delta)
            
        return deltas
