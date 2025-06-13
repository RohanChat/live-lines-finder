# Create a new file: src/live_scheduler.py
import time
import pandas as pd
from events_handler import EventsHandler
from notifier import TelegramNotifier
from odds_processor import OddsProcessor
from config import Config

class LiveSchedulerWithNotifications(EventsHandler):
    def __init__(self, include_arbitrage=True, include_mispriced=True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.notifier = TelegramNotifier(include_arbitrage=include_arbitrage, include_mispriced=include_mispriced)
        print("[LiveScheduler] Telegram notifier initialized.")
    
    def _run_event(self, event: dict):
        """Override to add notification sending"""
        from datetime import datetime, timezone
        
        ts = datetime.now(timezone.utc).isoformat()
        name = f"{event['home_team']} vs {event['away_team']}"
        print(f"[{ts}] ▶ Running processor for {name}")

        # Create processor
        proc = OddsProcessor(
            event,
            arb_thresh=self.arb_thresh,
            p_gap=self.p_gap,
            ev_thresh=self.ev_thresh,
            bootstrap=self.bootstrap
        )

        try:
            # Process odds and get results
            results = proc.process_odds_for_event(
                event,
                self.p_gap,
                self.ev_thresh,
                bootstrap=self.bootstrap,
                player=self.player,
                game=self.game,
                regions=self.regions,
                mode=self.mode,
                filepath=self.filepath,
                verbose=True
            )
            
            # Check if we got results with opportunities
            if results and len(results) >= 4:
                arb_df, arb_players_df, mispriced_df, mispriced_players_df = results[:4]
                
                # Check if there are any opportunities
                has_arb = not (arb_df.empty and arb_players_df.empty)
                has_mispriced = not (mispriced_df.empty and mispriced_players_df.empty)
                
                if has_arb or has_mispriced:
                    print(f"[{name}] Found opportunities! Sending notifications...")
                    
                    # Process and send notifications
                    self.notifier.process_dfs(arb_df, arb_players_df, mispriced_df, mispriced_players_df)
                    self.notifier.notify()
                    
                    print(f"[{name}] Notifications sent successfully!")
                else:
                    print(f"[{name}] No opportunities found, no notifications sent.")
            else:
                print(f"[{name}] No valid results returned from processor.")
                
        except Exception as err:
            print(f"[{name}] ERROR during processing → {err}")

if __name__ == "__main__":
    # Start the live scheduler with notifications
    scheduler = LiveSchedulerWithNotifications(
        include_arbitrage=True,   # Include arbitrage opportunities
        include_mispriced=True,   # Include mispriced/value betting opportunities
        p_gap=0.05,              # 5% price gap threshold
        ev_thresh=0.05,          # 5% expected value threshold  
        bootstrap=False,         # Don't use bootstrap mode
        arb_thresh=0.01,         # 1% arbitrage threshold
        player=True,             # Process player props
        game=True,               # Process game lines
        regions=Config.US,       # US sportsbooks
        mode="live",             # Live mode (not test)
        filepath="./odds_data",
        interval_minutes=3,      # Check every 3 minutes during games
    )

    try:
        print("🚀 Live scheduler started! Press Ctrl+C to stop.")
        print("📱 Make sure the Telegram bot is running in another terminal.")
        print("💰 Processing NBA games and sending notifications to subscribers...")
        
        # Keep the process alive
        while True:
            time.sleep(60)  # Sleep for 1 minute, then check again
            
    except (KeyboardInterrupt, SystemExit):
        scheduler.scheduler.shutdown()
        print("\n⏹️  Scheduler stopped.")