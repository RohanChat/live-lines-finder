import pytest
import asyncio
import json
import websockets
from unittest.mock import AsyncMock, MagicMock

from src.feeds.webhook.boltodds_webhook import BoltOddsWebhookAdapter
from src.feeds.models import FeedDelta, DeltaType

# Mark all tests in this file as asyncio
pytestmark = pytest.mark.asyncio

async def mock_boltodds_server(websocket, path=None):
    """A mock server that simulates the BoltOdds WebSocket behavior."""
    # 1. Wait for the subscription message
    subscription_request = await websocket.recv()
    assert json.loads(subscription_request)["action"] == "subscribe"

    # 2. Send a snapshot message
    snapshot_msg = {
        "type": "snapshot",
        "events": [{"id": "evt1", "data": "..."}, {"id": "evt2", "data": "..."}]
    }
    await websocket.send(json.dumps(snapshot_msg))

    # 3. Send an update message
    update_msg = {
        "type": "odds_update",
        "odds": {"event_id": "evt1", "market": "h2h", "price": 150}
    }
    await websocket.send(json.dumps(update_msg))

    # 4. Keep the connection open until the client disconnects
    try:
        await websocket.wait_closed()
    except websockets.exceptions.ConnectionClosed:
        pass

async def test_boltodds_adapter_flow():
    """
    Tests the full connect -> subscribe -> receive -> disconnect flow.
    """
    server = await websockets.serve(mock_boltodds_server, "localhost", 8765)
    
    adapter = BoltOddsWebhookAdapter(api_key="dummy_token")
    adapter.wss_url = "ws://localhost:8765" # Point adapter to the mock server

    mock_handler = AsyncMock()
    adapter.on_update(mock_handler)

    try:
        # Start the adapter, which connects, subscribes, and starts pumping messages
        await adapter.start(q=None) # The query is unused in this test

        # Give the client a moment to process messages
        await asyncio.sleep(0.1)

        # Stop the adapter
        await adapter.stop()

        # Assertions
        assert mock_handler.call_count == 3 # snapshot has 2 events, plus 1 update

        # Check the first delta from the snapshot
        delta1 = mock_handler.call_args_list[0].args[0]
        assert isinstance(delta1, FeedDelta)
        assert delta1.type == DeltaType.SNAPSHOT
        assert delta1.event_id == "evt1"

        # Check the second delta from the snapshot
        delta2 = mock_handler.call_args_list[1].args[0]
        assert isinstance(delta2, FeedDelta)
        assert delta2.type == DeltaType.SNAPSHOT
        assert delta2.event_id == "evt2"

        # Check the update delta
        delta3 = mock_handler.call_args_list[2].args[0]
        assert isinstance(delta3, FeedDelta)
        assert delta3.type == DeltaType.PRICE_UPDATE
        assert delta3.event_id == "evt1"
        assert delta3.payload["price"] == 150

    finally:
        # Clean up the server
        server.close()
        await server.wait_closed()
