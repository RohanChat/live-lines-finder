import asyncio
import sys
import os

# Add the project root to the Python path to resolve imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.feeds.webhook.unabated_webhook import UnabatedWebhook

async def main():
    """
    Tests the UnabatedWebhook client by connecting, receiving a few messages,
    and then shutting down.
    """
    print("Starting UnabatedWebhook test...")
    client = UnabatedWebhook()

    # Start the client in a background task
    client_task = asyncio.create_task(client._subscribe())

    # Run for a limited time (e.g., 30 seconds) to check for messages
    print("Running test for 30 seconds to capture some data...")
    try:
        await asyncio.sleep(30)
    finally:
        # Stop the client
        print("Stopping the client...")
        await client.stop()
        # Wait for the task to finish cleanly
        await client_task
        print("UnabatedWebhook test finished.")

if __name__ == "__main__":
    # Ensure you run this script from the project's root directory, for example:
    # python tests/test_unabated_webhook.py
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Test interrupted by user.")
