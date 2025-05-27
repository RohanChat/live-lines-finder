import pytz
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
import logging

from config          import Config
from event_fetcher   import EventFetcher
from odds_processor  import process_odds_for_event

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = logging.getLogger(__name__)

class EventsHandler:
    def __init__(
        self,
        p_gap: float,
        ev_thresh: float,
        bootstrap: bool = False,
        player: bool = True,
        game: bool = False,
        regions=Config.US,
        mode: str = "live",
        filepath: str = "./odds_data",
        interval_minutes: int = 5,
    ):
        self.fetcher    = EventFetcher()
        self.scheduler  = BackgroundScheduler(timezone=pytz.UTC)
        self.p_gap      = p_gap
        self.ev_thresh  = ev_thresh
        self.bootstrap  = bootstrap
        self.player     = player
        self.game       = game
        self.regions    = regions
        self.mode       = mode
        self.filepath   = filepath
        self.interval   = interval_minutes

        # 1) Schedule a daily job at midnight UTC to refresh today's events
        self.scheduler.add_job(
            self.schedule_todays_events,
            CronTrigger(hour=0, minute=0),
            id="daily_event_refresh"
        )

        # 2) Run once immediately on startup
        self.schedule_todays_events()

        # 3) Start the background scheduler
        self.scheduler.start()
        print("[EventsHandler] Scheduler started.")

    def schedule_todays_events(self):
        now = datetime.now(timezone.utc)
        print(f"[{now.isoformat()}] Scheduling today's events…")
        events = self.fetcher.get_todays_events()
        for evt in events:
            self._schedule_event_jobs(evt)

    def _schedule_event_jobs(self, event: dict):
        """
        For a single event dict, schedule:
          - A one‐time run at T_start – 15m
          - An interval run every self.interval minutes from T_start + 15m until T_start + 4h
        """
        event_id   = event["id"]
        name       = f"{event['home_team']} vs {event['away_team']}"
        commence   = datetime.fromisoformat(event["commence_time"])
        now        = datetime.now(timezone.utc)

        t_pre      = commence - timedelta(minutes=15)
        t_interval = commence + timedelta(minutes=15)
        t_end      = commence + timedelta(hours=4)

        pre_job_id = f"pre_{event_id}"
        int_job_id = f"int_{event_id}"

        # Remove any existing jobs for this event
        for jid in (pre_job_id, int_job_id):
            if self.scheduler.get_job(jid):
                self.scheduler.remove_job(jid)

        # Schedule the pre-game check
        if t_pre > now:
            self.scheduler.add_job(
                self._run_event,
                trigger=DateTrigger(run_date=t_pre),
                args=[event],
                id=pre_job_id,
                max_instances=1,
            )
            print(f"[{name}] Scheduled pre-game check at {t_pre.isoformat()}")

        # Schedule the recurring post-start checks
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
                id=int_job_id,
                max_instances=1,
            )
            print(
                f"[{name}] Scheduled interval checks every {self.interval}m "
                f"from {start_date.isoformat()} to {t_end.isoformat()}"
            )

    def _run_event(self, event: dict):
        """
        Wrapper to call your odds-processor with the stored parameters.
        """
        now  = datetime.now(timezone.utc).isoformat()
        name = f"{event['home_team']} vs {event['away_team']}"
        print(f"[{now}] Running processor for {name}")
        try:
            process_odds_for_event(
                event,
                self.p_gap,
                self.ev_thresh,
                bootstrap=self.bootstrap,
                player=self.player,
                game=self.game,
                regions=self.regions,
                mode=self.mode,
                filepath=self.filepath,
                verbose=False
            )
        except Exception as err:
            print(f"[{name}] Error during processing: {err}")
