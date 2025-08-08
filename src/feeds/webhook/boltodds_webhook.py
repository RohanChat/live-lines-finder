import asyncio
import json
import os
from datetime import datetime
import websockets

from config import Config
from feeds.webhook.webhook import WebhookFeed


class BoltOddsWebhook(WebhookFeed):
    """Receive odds updates via the BoltOdds websocket feed."""

    def __init__(self) -> None:
        # The base class __init__ is called, but we don't need to pass params
        # as BoltOdds uses a different authentication method.
        super().__init__()
        
        token = Config.BOLTODDS_TOKEN
        if not token:
            raise ValueError("BOLTODDS_API_KEY not found in environment variables.")
        
        self.wss_url = f"wss://spro.agency/api?key={token}"
        self.client_name = "BoltOddsClient"

    async def _subscribe(self) -> None:
        """
        Connect to the BoltOdds websocket, subscribe to data streams,
        and process incoming messages.
        """
        print(f"Connecting to {self.client_name} at {self.wss_url.split('?')[0]}")
        self._is_running = True
        
        while self._is_running:
            try:
                async with websockets.connect(self.wss_url) as websocket:
                    print(f"{self.client_name} connected successfully.")
                    
                    # On connection, BoltOdds may send an acknowledgement.
                    ack_message = await websocket.recv()
                    print(f"Received acknowledgement: {ack_message}")

                    # Define the subscription filters
                    subscribe_message = {
                        "action": "subscribe",
                        "filters": {
                            "sports": ["NBA", "MLB"],
                            "sportsbooks": ["draftkings", "betmgm"],
                            "markets": ["Moneyline", "Spread", "Total"]
                        }
                    }
                    await websocket.send(json.dumps(subscribe_message))
                    print("Sent subscription request.")

                    # Listen for incoming messages
                    while self._is_running:
                        message = await websocket.recv()
                        await self._process_message(message)

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
        print(f"Received data: {message[:200]}...") # Print a snippet of the message

        # Ensure the directory exists
        output_dir = "odds_data/boltodds"
        os.makedirs(output_dir, exist_ok=True)

        # Save the raw data to a file
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        file_path = os.path.join(output_dir, f"boltodds_data_{timestamp}.json")
        
        try:
            # We save the raw message string directly
            with open(file_path, 'w') as f:
                f.write(message)
            
            # Also, let's parse it to notify any registered handlers with structured data
            data = json.loads(message)
            self._notify(data)
        
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON message: {e}")
            print(f"Raw message was saved to {file_path}")
        except Exception as e:
            print(f"An error occurred during message processing: {e}")

    def stop(self) -> None:
        """Stop the websocket subscription."""
        print(f"Stopping {self.client_name} feed...")
        self._is_running = False