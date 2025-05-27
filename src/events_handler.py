import threading
import time
from datetime import datetime, timedelta, timezone
from .config import Config
from .event_fetcher import EventFetcher
from .odds_processor import process_odds_for_event, run_props_for_duration

class EventsHandler:
    def __init__(self, event_queue):
        self.event_queue = event_queue

    # Placeholder for the repeated listener logic
    def iterative_props_listener(self, event, markets, key="player", region=Config.US, interval_seconds=15):
        event_name = f"{event['home_team']} vs. {event['away_team']}"
        print(f"[{event_name}] Starting iterative listener at {datetime.now(timezone.utc)}")
        
        try:
            while True:
                print(f"[{event_name}] Polling at {datetime.now(timezone.utc)}")
                # Replace this with your actual logic:
                # start_props_listener(events=[event], markets=markets, ...)
                time.sleep(interval_seconds)
        except Exception as e:
            print(f"[{event_name}] Listener stopped with error: {e}")

    # Handles full lifecycle for one event
    def handle_event_schedule(event, player=True, game_period=False, alternate=False, game=False, key="player_all", region=Config.US, interval_seconds=60):
        event_name = f"{event['home_team']} vs. {event['away_team']}"
        commence_time = datetime.fromisoformat(event["commence_time"])

        # Step 0: Now
        print("Conducting quick inital odds check")
        try:
            process_odds_for_event(event, player=True, game_period=False,
                                alternate=False, game=False)
        except Exception as e:
            print(f"[{event['home_team']} vs {event['away_team']}] "
                f"initial check failed → {e}")

        # Step 1: 15 minutes BEFORE
        time_to_15_before = (commence_time - timedelta(minutes=15)) - datetime.now(timezone.utc)
        if time_to_15_before.total_seconds() > 0:
            print(f"[{event_name}] Sleeping until 15 minutes before start ({time_to_15_before.total_seconds()}s)")
            time.sleep(time_to_15_before.total_seconds())
        try:
            print(f"[{event_name}] It's now 15 mins before the game. Checking odds.")
            process_odds_for_event(event, player=True, game_period=False, alternate=False, game=False)
        except Exception as e:
            print(f"[{event_name}] Error during pre-game odds check: {e}")


        # Step 2: At commence time
        time_to_commence = (commence_time - datetime.now(timezone.utc))
        if time_to_commence.total_seconds() > 0:
            print(f"[{event_name}] Sleeping until commence time ({time_to_commence.total_seconds()}s)")
            time.sleep(time_to_commence.total_seconds())
        try:
            print(f"[{event_name}] It's now game time. Conducting odds check.")
            process_odds_for_event(event, player=True, game_period=False, alternate=False, game=False)
        except Exception as e:
            print(f"[{event_name}] Error during commence-time odds check: {e}")



        # Step 3: 15 minutes AFTER
        time_to_post_commence = (commence_time + timedelta(minutes=15)) - datetime.now(timezone.utc)
        if time_to_post_commence.total_seconds() > 0:
            print(f"[{event_name}] Sleeping until 15 mins after start ({time_to_post_commence.total_seconds()}s)")
            time.sleep(time_to_post_commence.total_seconds())
        
        print(f"[{event_name}] Starting 3.5 hour prop checker in background thread.")
        duration_thread = threading.Thread(
            target=run_props_for_duration,
            args=(event,),
            kwargs={"duration_minutes": 210, "interval_minutes": 5, "player": player, "game_period": game_period, "alternate": alternate, "game": game}
        )
        duration_thread.start()

    # Launch all event threads
    def launch_event_listeners(self, events_df, player_bool=True, game_period_bool=False, alternate_bool=False, game_bool=False):
        for _, event in events_df.iterrows():
            thread = threading.Thread(target=self.handle_event_schedule, args=(event,), kwargs={"player": player_bool, "game_period": game_period_bool, "alternate": alternate_bool, "game": game_bool})
            thread.start()