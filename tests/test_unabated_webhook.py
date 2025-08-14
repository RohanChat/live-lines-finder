import pytest
import asyncio
import json
import websockets
from unittest.mock import AsyncMock

from src.feeds.webhook.unabated_webhook import UnabatedWsAdapter
from src.feeds.models import FeedDelta, DeltaType

pytestmark = pytest.mark.asyncio

async def mock_unabated_server(websocket, path=None):
    """A mock server that simulates the Unabated GraphQL-WS handshake."""
    # 1. Expect 'connection_init' and respond with 'connection_ack'
    init_msg = await websocket.recv()
    assert json.loads(init_msg)["type"] == "connection_init"
    await websocket.send(json.dumps({"type": "connection_ack"}))

    # 2. Expect 'start' for the subscription
    start_msg = await websocket.recv()
    assert json.loads(start_msg)["type"] == "start"

    # 3. Send a sample 'data' message
    data_msg = {
        "type": "data",
        "id": json.loads(start_msg)["id"],
        "payload": {
            "data": {
                "marketLineUpdate": {
                    "leagueId": 1,
                    "marketLines": [{"price": -110}]
                }
            }
        }
    }
    await websocket.send(json.dumps(data_msg))

    try:
        await websocket.wait_closed()
    except websockets.exceptions.ConnectionClosed:
        pass

async def test_unabated_ws_adapter_manual_protocol():
    """
    Tests the UnabatedWsAdapter with a mock server that speaks the GQL-WS protocol.
    """
    server = await websockets.serve(mock_unabated_server, "localhost", 8766)

    adapter = UnabatedWsAdapter(api_key="dummy", host="dummy.host")
    # Point the adapter to the mock server
    adapter.wss_url = "ws://localhost:8766"

    mock_handler = AsyncMock()
    adapter.on_update(mock_handler)

    try:
        await adapter.start(q=None)
        await asyncio.sleep(0.1)
        await adapter.stop()

        mock_handler.assert_called_once()
        delta = mock_handler.call_args.args[0]

        assert isinstance(delta, FeedDelta)
        assert delta.type == DeltaType.MARKET_UPDATE
        assert delta.payload["leagueId"] == 1
        assert delta.payload["marketLines"][0]["price"] == -110

    finally:
        server.close()
        await server.wait_closed()
