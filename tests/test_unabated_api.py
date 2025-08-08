print("--- Test script starting ---")
import sys
import os
import json
from datetime import datetime
print("--- Standard modules imported ---")

# Add 'src' to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
print(f"--- sys.path updated: {sys.path[0]} ---")

print("--- Importing UnabatedAPI client ---")
from feeds.api.unabated_api import UnabatedAPI
print("--- UnabatedAPI client imported successfully ---")

def main():
    """
    Initializes the UnabatedAPI client and tests its methods.
    """
    print("Initializing Unabated API client for testing...")
    try:
        client = UnabatedAPI()

        # --- Test get_bet_types ---
        print("\n--- Testing get_bet_types() ---")
        bet_types_response = client.get_bet_types()
        print("\n--- Raw API Response for get_bet_types ---")
        print(json.dumps(bet_types_response, indent=4))

        # The actual list is nested inside the response dictionary
        bet_types = bet_types_response.get('bet_types', [])
        
        if bet_types:
            print(f"Successfully retrieved {len(bet_types)} bet types.")
            save_data(bet_types, "unabated_bet_types")
            print("\nSample of first 3 bet types:")
            print(json.dumps(bet_types[:3], indent=4))
        else:
            print("No bet types were returned.")

        # --- Test get_upcoming_events for NBA ---
        print("\n--- Testing get_upcoming_events(league='nba') ---")
        upcoming_events_response = client.get_upcoming_events(league="nba")
        print("\n--- Raw API Response for get_upcoming_events ---")
        print(json.dumps(upcoming_events_response, indent=4))

        # The actual list is nested inside the response dictionary
        upcoming_nba_events = upcoming_events_response.get('events', [])

        if upcoming_nba_events:
            print(f"Successfully retrieved {len(upcoming_nba_events)} upcoming NBA events.")
            save_data(upcoming_nba_events, "unabated_nba_upcoming")
            print("\nSample of first event:")
            if upcoming_nba_events:
                print(json.dumps(upcoming_nba_events[0], indent=4))
        else:
            print("No upcoming NBA events were returned.")

    except Exception as e:
        print(f"\nAn error occurred: {e}")

def save_data(data: list, filename_prefix: str):
    """Saves data to a timestamped JSON file."""
    output_dir = "odds_data/unabated"
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(output_dir, f"{filename_prefix}_{timestamp}.json")
    
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=4)
    
    print(f"Data saved to {file_path}")


if __name__ == "__main__":
    main()
