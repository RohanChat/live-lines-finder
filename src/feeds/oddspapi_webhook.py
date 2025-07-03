from __future__ import annotations

import os
import json
import asyncio
import websockets
from typing import Any, Dict

from .webhook import WebhookFeed


class OddsPAPIWebhook(WebhookFeed):
    """Receive odds updates via the OddspAPI websocket feed."""

    def __init__(
        self,
        wss_url: str | None = None,
        client_name: str | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__()
        self.wss_url = wss_url or os.getenv("WSS_URL")
        self.client_name = client_name or os.getenv("CLIENT_NAME")
        self.api_key = api_key or os.getenv("CLIENT_API_KEY")

    async def _subscribe(self) -> None:
        if not self.wss_url or not self.client_name or not self.api_key:
            raise RuntimeError("Missing websocket configuration for OddsPAPI")

        async with websockets.connect(self.wss_url) as websocket:
            await websocket.send(f"subscribe:{self.client_name}:{self.api_key}")
            while True:
                message = await websocket.recv()
                try:
                    data: Dict[str, Any] = json.loads(message)
                except json.JSONDecodeError:
                    continue
                self._notify(data)

    def start(self) -> None:
        """Run the websocket subscription until cancelled."""
        asyncio.run(self._subscribe())
