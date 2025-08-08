print("--- Script starting ---")
import sys
import os
import asyncio
print("--- Python modules imported ---")

# This ensures that the 'src' directory is in the Python path,
# allowing imports like 'from config import Config' to work correctly.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
print(f"--- sys.path updated: {sys.path[0]} ---")

print("--- Importing BoltOddsWebhook ---")
from feeds.webhook.boltodds_webhook import BoltOddsWebhook
print("--- BoltOddsWebhook imported successfully ---")

def main():
    """
    Initializes and starts the BoltOddsWebhook client for testing.
    """
    print("Initializing BoltOdds Webhook client...")
    client = BoltOddsWebhook()
    
    try:
        print("Starting client... Press Ctrl+C to stop.")
        # The start() method from the base class runs the _subscribe method in a loop.
        client.start()
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received.")
    finally:
        print("Stopping client...")
        # The stop() method from the base class sets the flag to stop the loop.
        client.stop()
        print("Client stopped.")

if __name__ == "__main__":
    main()
