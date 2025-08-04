# src/events_handler.py

import time
import pandas as pd
import pytz
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron     import CronTrigger
from apscheduler.triggers.date     import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config            import Config
from feeds.the_odds_api     import TheOddsAPI
from analysis.odds_processor    import OddsProcessor

class EventsHandler:
    def __init__(
        self,
        p_gap: float,
        ev_thresh: float,
        bootstrap: bool = False,
        arb_thresh: float = 0.01,
        player:    bool  = True,
        game:      bool  = False,
        regions           = Config.US,
        mode:      str   = "live",
        filepath:  str   = "./odds_data",
        interval_minutes: int = 5,
    ):
        pd.set_option("display.max_columns", None)  # Show all columns
        pd.set_option("display.width", None)        # Use full terminal width
        pd.set_option("display.expand_frame_repr", False)  # Don't wrap rows across lines
        self.fetcher    = TheOddsAPI()
        self.scheduler  = BackgroundScheduler(timezone=pytz.UTC)

        # store your thresholds & flags
        self.p_gap      = p_gap
        self.ev_thresh  = ev_thresh
        self.arb_thresh = arb_thresh
        self.bootstrap  = bootstrap
        self.player     = player
        self.game       = game
        self.regions    = regions
        self.mode       = mode
        self.filepath   = filepath
        self.interval   = interval_minutes

        # 1) daily at midnight UTC, refresh & schedule
        self.scheduler.add_job(
            self._schedule_all_events,
            CronTrigger(hour=0, minute=0),
            id="daily_event_refresh"
        )

        # 2) run once now
        self._schedule_all_events()
        # 2a) initial check right on launch: process odds immediately for today's events
        print("[EventsHandler] Running initial check for today's events…")
        for evt in self.fetcher.get_events_between_hours(6, 24):
            self._run_event(evt)

        # 3) start the scheduler
        self.scheduler.start()
        print("[EventsHandler] Scheduler started.")

    def _schedule_all_events(self):
        now = datetime.now(timezone.utc)
        print(f"[{now.isoformat()}] Refreshing & scheduling today's events…")
        events = self.fetcher.get_events_between_hours(6, 24)
        for evt in events:
            self._schedule_event(evt)

    def _schedule_event(self, event: dict):
        eid      = event["id"]
        name     = f"{event['home_team']} vs {event['away_team']}"
        commence = datetime.fromisoformat(event["commence_time"])
        now      = datetime.now(timezone.utc)

        t_pre      = commence - timedelta(minutes=15)
        t_interval = commence + timedelta(minutes=15)
        t_end      = commence + timedelta(hours=4)

        pre_id = f"pre_{eid}"
        int_id = f"int_{eid}"

        # clear any old jobs
        for jid in (pre_id, int_id):
            if self.scheduler.get_job(jid):
                self.scheduler.remove_job(jid)

        # 1-time, 15m before
        if t_pre > now:
            self.scheduler.add_job(
                self._run_event,
                trigger=DateTrigger(run_date=t_pre),
                args=[event],
                id=pre_id,
                max_instances=1,
            )
            print(f"[{name}] scheduled pre-game @ {t_pre.isoformat()}")

        # interval from +15m → +4h
        if t_interval < t_end:
            start_date = max(t_interval, now)
            self.scheduler.add_job(
                self._run_event,
                trigger=IntervalTrigger(
                    minutes=self.interval,
                    start_date=start_date,
                    end_date=t_end
                ),
                args=[event],
                id=int_id,
                max_instances=1,
            )
            print(
                f"[{name}] scheduled every {self.interval}m "
                f"from {start_date.isoformat()} to {t_end.isoformat()}"
            )

    def _run_event(self, event: dict):
        ts   = datetime.now(timezone.utc).isoformat()
        name = f"{event['home_team']} vs {event['away_team']}"
        print(f"[{ts}] ▶ Running processor for {name}")

        # Correctly pass `event` as first arg to OddsProcessor
        proc = OddsProcessor(
            event,
            feed=self.fetcher,
            arb_thresh=self.arb_thresh,
            p_gap=self.p_gap,
            ev_thresh=self.ev_thresh,
            bootstrap=self.bootstrap
        )

        try:
            proc.process_odds_for_event(
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
        except Exception as err:
            print(f"[{name}] ERROR during processing → {err}")


if __name__ == "__main__":
    # instantiate with your desired params
    handler = EventsHandler(
        p_gap=0.1,
        ev_thresh=0.10,
        bootstrap=False,
        arb_thresh=0.01,
        player=True,
        game=True,
        regions=Config.US,
        mode="live",
        filepath="./odds_data",
        interval_minutes=5,
    )

    try:
        # keep the process alive so the scheduler can run
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        handler.scheduler.shutdown()
        print("Scheduler stopped.")
