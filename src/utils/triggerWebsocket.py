import os
import asyncio
import websockets
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get environment variables
wss_url = os.getenv('WSS_URL')
CLIENT_NAME = os.getenv('CLIENT_NAME')
CLIENT_API_KEY = os.getenv('CLIENT_API_KEY')

async def subscribe_to_websocket():
    try:
        async with websockets.connect(wss_url) as websocket:
            print(f"Connected to {wss_url}")

            # Send a subscription message
            await websocket.send(f"subscribe:{CLIENT_NAME}:{CLIENT_API_KEY}")
            print(f"{CLIENT_NAME} started subscription to ODDS-API {CLIENT_API_KEY}")

            # Listen for incoming messages from the server
            while True:
                message = await websocket.recv()
                print(f"Received message: {message}")
    except Exception as e:
        print(f"Failed to connect: {e}")


# Run the WebSocket client
asyncio.run(subscribe_to_websocket())
