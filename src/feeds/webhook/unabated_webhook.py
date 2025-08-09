from __future__ import annotations

import os
import json
import asyncio
import websockets
import base64
import uuid
from datetime import datetime
from typing import Any, Dict

from src.config import Config
from .webhook import WebhookFeed


class UnabatedWebhook(WebhookFeed):
    """Receive odds updates via the Unabated GraphQL websocket feed."""

    def __init__(self) -> None:
        super().__init__()
        self.client_name = "UnabatedWebhookClient"
        
        # Load credentials from config
        self.host = Config.UNABATED_REALTIME_API_HOST
        self.api_key = Config.UNABATED_API_KEY

        # --- Add this for debugging ---
        print(f"--- DEBUG: Loaded UNABATED_REALTIME_API_HOST = '{self.host}' (Type: {type(self.host)}) ---")
        # --- End of debug code ---
        
        if not self.host or not self.api_key:
            raise ValueError("Missing Unabated realtime host or API key in environment variables.")

        # Construct the special WebSocket URL required by AWS AppSync
        endpoint = f"wss://{self.host}/graphql/realtime"
        header = base64.b64encode(json.dumps({"host": self.host, "Authorization": self.api_key}).encode()).decode()
        payload = base64.b64encode(b"{}").decode()
        self.wss_url = f"{endpoint}?header={header}&payload={payload}"

    async def _subscribe(self) -> None:
        """
        Connect to the Unabated websocket, subscribe to the GraphQL feed,
        and process incoming messages.
        """
        print(f"Connecting to {self.client_name}...")
        self._is_running = True

        while self._is_running:
            try:
                async with websockets.connect(self.wss_url, subprotocols=['graphql-ws']) as websocket:
                    print(f"{self.client_name} connected successfully.")
                    
                    # 1. Send connection_init message
                    await websocket.send(json.dumps({
                        "type": "connection_init",
                        "payload": {"authorization": {"host": self.host, "Authorization": self.api_key}}
                    }))

                    # 2. Prepare the subscription payload
                    subscription_id = str(uuid.uuid4())
                    subscription_query = """
                        subscription marketLineUpdate {
                          marketLineUpdate {
                            leagueId
                            marketSourceGroup
                            messageId
                            messageTimestamp
                            marketLines {
                              marketId
                              marketLineId
                              marketSourceId
                              points
                              price
                              statusId
                              edge
                              marketLineKey
                              modifiedOn
                            }
                          }
                        }
                    """
                    start_payload = {
                        "id": subscription_id,
                        "type": "start",
                        "payload": {
                            "data": json.dumps({"query": subscription_query}),
                            "extensions": {
                                "authorization": {
                                    "host": self.host,
                                    "Authorization": self.api_key,
                                }
                            }
                        }
                    }

                    # 3. Listen for messages and handle the handshake
                    while self._is_running:
                        message = await websocket.recv()
                        parsed_message = json.loads(message)
                        msg_type = parsed_message.get("type")

                        if msg_type == "connection_ack":
                            print("Connection acknowledged. Sending subscription request...")
                            await websocket.send(json.dumps(start_payload))
                        
                        elif msg_type == "start_ack":
                            print("Subscription acknowledged. Listening for data...")

                        elif msg_type == "data":
                            await self._process_message(message)
                        
                        elif msg_type == "ka":
                            # Keep-alive message, ignore
                            continue

                        elif msg_type == "error":
                            print(f"Subscription error: {parsed_message}")
                        
                        else:
                            print(f"Unhandled message type '{msg_type}': {parsed_message}")

            except websockets.ConnectionClosed as e:
                print(f"Connection to {self.client_name} closed: {e}")
                if not self._is_running:
                    break
                print("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"An error occurred with {self.client_name}: {e}")
                if not self._is_running:
                    break
                print("Attempting to reconnect in 5 seconds...")
                await asyncio.sleep(5)

    async def _process_message(self, message: str) -> None:
        """Process and save incoming websocket message."""
        try:
            data = json.loads(message)
            result = data.get("payload", {}).get("data", {}).get("marketLineUpdate")
            
            if not result:
                print(f"Received non-data message: {data}")
                return

            print(f"Received update for league {result.get('leagueId')} with {len(result.get('marketLines', []))} lines.")

            # Ensure the directory exists
            output_dir = "odds_data/unabated"
            os.makedirs(output_dir, exist_ok=True)

            # Save the raw data to a file
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
            file_path = os.path.join(output_dir, f"unabated_data_{timestamp}.json")
            
            with open(file_path, 'w') as f:
                json.dump(result, f, indent=4)
            
            self._notify(result)
        
        except Exception as e:
            print(f"An error occurred during message processing: {e}")
