# Create a new file: src/live_scheduler.py
import time
import pandas as pd
import asyncio
import pytz
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from events_handler import EventsHandler
from notifier import TelegramNotifier
from analysis.odds_processor import OddsProcessor
from config import Config
from feeds.the_odds_api import TheOddsAPI

class LiveSchedulerWithNotifications(EventsHandler):
    def __init__(self, include_arbitrage=True, include_mispriced=True, links_only=True, *args, **kwargs):
        # Initialize the notifier FIRST, before calling parent constructor
        self.notifier = TelegramNotifier(include_arbitrage=include_arbitrage, include_mispriced=include_mispriced, links_only=links_only)
        print("[LiveScheduler] Telegram notifier initialized.")
        
        # Store args for custom initialization
        self._init_args = args
        self._init_kwargs = kwargs
        
        # Initialize our own attributes instead of calling super().__init__()
        self._initialize_async_scheduler(*args, **kwargs)
        
    def _initialize_async_scheduler(self, p_gap, ev_thresh, bootstrap=False, arb_thresh=0.01, 
                                   player=True, game=False, regions=Config.US, mode="live", 
                                   filepath="./odds_data", interval_minutes=5):
        """Initialize async scheduler instead of the parent's sync scheduler."""
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", None)
        pd.set_option("display.expand_frame_repr", False)
        
        self.fetcher = TheOddsAPI()
        self.scheduler = AsyncIOScheduler(timezone=pytz.UTC)  # Use AsyncIOScheduler

        # Store thresholds & flags
        self.p_gap = p_gap
        self.ev_thresh = ev_thresh
        self.arb_thresh = arb_thresh
        self.bootstrap = bootstrap
        self.player = player
        self.game = game
        self.regions = regions
        self.mode = mode
        self.filepath = filepath
        self.interval = interval_minutes

        # Add jobs to async scheduler
        self.scheduler.add_job(
            self._schedule_all_events_async,
            CronTrigger(hour=0, minute=0),
            id="daily_event_refresh"
        )

    async def _schedule_all_events_async(self):
        """Async version of _schedule_all_events."""
        ts = datetime.now(timezone.utc).isoformat()
        print(f"[{ts}] Refreshing & scheduling today's events…")

        # Clear existing event-specific jobs
        for job in self.scheduler.get_jobs():
            if job.id != "daily_event_refresh":
                job.remove()

        # Get events for today
        events = self.fetcher.get_events_between_hours(6, 24)
        for event in events:
            event_name = f"{event['home_team']} vs {event['away_team']}"
            event_time = datetime.fromisoformat(event['commence_time'].replace('Z', '+00:00'))

            # Schedule pre-game run (15 minutes before start)
            pre_game_time = event_time - timedelta(minutes=15)
            if pre_game_time > datetime.now(timezone.utc):
                self.scheduler.add_job(
                    self._run_event,
                    DateTrigger(run_date=pre_game_time),
                    args=[event],
                    id=f"pre_game_{event['id']}"
                )
                print(f"[{event_name}] scheduled pre-game @ {pre_game_time.isoformat()}")

            # Schedule live runs (every N minutes from 15 min after start to 4 hours later)
            live_start = event_time + timedelta(minutes=15)
            live_end = event_time + timedelta(hours=4)
            
            if live_end > datetime.now(timezone.utc):
                self.scheduler.add_job(
                    self._run_event,
                    IntervalTrigger(minutes=self.interval, start_date=live_start, end_date=live_end),
                    args=[event],
                    id=f"live_{event['id']}"
                )
                print(f"[{event_name}] scheduled every {self.interval}m from {live_start.isoformat()} to {live_end.isoformat()}")

    async def start_async(self):
        """Start the async scheduler."""
        print("[LiveScheduler] Starting async scheduler...")
        
        # Run initial event scheduling
        await self._schedule_all_events_async()
        
        # Run initial check for today's events
        print("[EventsHandler] Running initial check for today's events…")
        events = self.fetcher.get_events_between_hours(6, 24)
        for event in events:
            await self._run_event(event)
        
        # Start the scheduler
        self.scheduler.start()
        print("[EventsHandler] Async scheduler started.")
    
    async def _run_event(self, event: dict):
        """Override to add notification sending - now async"""
        from datetime import datetime, timezone
        
        ts = datetime.now(timezone.utc).isoformat()
        name = f"{event['home_team']} vs {event['away_team']}"
        print(f"[{ts}] ▶ Running processor for {name}")

        # Create processor
        proc = OddsProcessor(
            event,
            feed=self.fetcher,
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
                    
                    # Process and send notifications (now async)
                    self.notifier.process_dfs(arb_df, arb_players_df, mispriced_df, mispriced_players_df)
                    await self.notifier.notify_async()
                    
                    print(f"[{name}] Notifications sent successfully!")
                else:
                    print(f"[{name}] No opportunities found, no notifications sent.")
            else:
                print(f"[{name}] No valid results returned from processor.")
                
        except Exception as err:
            print(f"[{name}] ERROR during processing → {err}")

if __name__ == "__main__":
    async def main():
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
            
            # Start the async scheduler
            await scheduler.start_async()
            
            # Keep the process alive
            while True:
                await asyncio.sleep(60)  # Sleep for 1 minute, then check again
                
        except KeyboardInterrupt:
            print("\n⏹ Stopping scheduler...")
            scheduler.scheduler.shutdown()
            print("✅ Scheduler stopped.")
        except Exception as e:
            print(f"❌ Error: {e}")
            scheduler.scheduler.shutdown()

    # Run the async main function
    asyncio.run(main())