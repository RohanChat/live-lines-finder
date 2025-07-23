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
