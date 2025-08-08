from __future__ import annotations

import asyncio
import json
import os
from typing import Callable, List, Dict, Any, Iterable

import websockets
from dotenv import load_dotenv

from config import Config

from ..base import OddsFeed


class WebhookFeed(OddsFeed):
    """Implementation of :class:`OddsFeed` for webhook/websocket based providers."""

    def __init__(self, wss_url: str = None, client_name: str = None, api_key: str = None) -> None:
        super().__init__()  # ✅ Initialize base class configuration
        
        # Websocket configuration
        self.wss_url = wss_url or Config.ODDSPAPI_WSS_URL
        self.client_name = client_name or Config.ODDSPAPI_CLIENT_NAME
        self.api_key = api_key or Config.ODDSPAPI_CLIENT_API_KEY
        
        # Handler system
        self._handlers: List[Callable[[Dict[str, Any]], None]] = []
        self._is_running = False

    async def _subscribe(self) -> None:
        """Subscribe to websocket feed and process incoming messages."""
        if not self.wss_url or not self.client_name or not self.api_key:
            raise RuntimeError(
                "Missing websocket configuration. Please provide wss_url, client_name, and api_key "
                "either as parameters or environment variables (WSS_URL, CLIENT_NAME, CLIENT_API_KEY)"
            )

        print(f"Connecting to {self.wss_url}")
        
        try:
            async with websockets.connect(self.wss_url) as websocket:
                # Send subscription message
                subscription_msg = f"subscribe:{self.client_name}:{self.api_key}"
                await websocket.send(subscription_msg)
                print(f"{self.client_name} started subscription")
                
                self._is_running = True
                
                # Listen for incoming messages
                while self._is_running:
                    try:
                        message = await websocket.recv()
                        await self._process_message(message)
                    except websockets.exceptions.ConnectionClosed:
                        print("Websocket connection closed")
                        break
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        continue
                        
        except Exception as e:
            print(f"Failed to connect to websocket: {e}")
            raise

    async def _process_message(self, message: str) -> None:
        """Process incoming websocket message."""
        try:
            data: Dict[str, Any] = json.loads(message)
            print(f"Received data: {data}")
            self._notify(data)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON message: {e}")
            print(f"Raw message: {message}")

    def start(self) -> None:
        """Run the websocket subscription until cancelled."""
        print("Starting websocket feed...")
        try:
            asyncio.run(self._subscribe())
        except KeyboardInterrupt:
            print("Websocket feed stopped by user")
        except Exception as e:
            print(f"Websocket feed error: {e}")
            raise
    
    def stop(self) -> None:
        """Stop the websocket subscription."""
        self._is_running = False
        print("Stopping websocket feed...")
        
    # Registration hooks -------------------------------------------------
    def register_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback to process incoming webhook payloads."""
        self._handlers.append(handler)
        print(f"Registered handler: {handler.__name__}")

    def _notify(self, data: Dict[str, Any]) -> None:
        """Notify all registered handlers of new data."""
        for handler in self._handlers:
            try:
                handler(data)
            except Exception as e:
                print(f"Error in handler {handler.__name__}: {e}")

    # OddsFeed API -------------------------------------------------------
    # These methods don't make sense for a real-time webhook feed
    # They could either raise NotImplementedError or return cached data
    
    def get_todays_events(self, commence_time_from: str, commence_time_to: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("WebhookFeed is real-time only. Use register_handler() to process live data.")

    def get_events_between_hours(self, prev_hours: int = 6, next_hours: int = 24) -> List[Dict[str, Any]]:
        raise NotImplementedError("WebhookFeed is real-time only. Use register_handler() to process live data.")

    def get_events_in_next_hours(self, hours: int = 24) -> List[Dict[str, Any]]:
        raise NotImplementedError("WebhookFeed is real-time only. Use register_handler() to process live data.")

    def get_props_for_todays_events(self, events: Iterable[Dict[str, Any]], markets: str, regions: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("WebhookFeed is real-time only. Use register_handler() to process live data.")

    def get_game_odds(self, markets: str, regions: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("WebhookFeed is real-time only. Use register_handler() to process live data.")