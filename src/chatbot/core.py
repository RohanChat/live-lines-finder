from __future__ import annotations

from functools import wraps
import json
import os
import logging
from typing import Iterable, Sequence, Dict, Any, Optional

import openai

from config import Config
from database import get_db_session
from database.models import UserSubscription
from database.session import get_user_by_phone
from messaging.base import BaseMessagingClient
from feeds.base import OddsFeed
from analysis.base import AnalysisEngine

logger = logging.getLogger(__name__)

def require_subscription(fn):
    @wraps(fn)
    async def wrapper(self, update, context):
        # 1. Get the unique chat identifier from the messaging platform.
        # This works for the mock client, Telegram (integer ID), and iMessage (phone number).
        chat_id = getattr(update.effective_chat, "id", None) or getattr(update, "chat_id", None)
        if not chat_id:
            logger.warning("Could not determine chat_id from update.")
            return

        db = next(get_db_session())
        try:
            # 2. Find the user record using the chat_id.
            user = get_user_by_phone(db, chat_id)

            # 3. Check if the user exists and has a phone number registered.
            if not user or not user.phone:
                await self.platform.send_message(
                    chat_id,
                    "Your account is not fully set up. Please register your phone number on our website to continue."
                )
                return

            # 4. Check for a specific, active subscription for that user.
            active_subscription = db.query(UserSubscription).filter(
                UserSubscription.user_id == user.id,
                UserSubscription.active == True,
                UserSubscription.product_id == self.product_id
            ).first()

            if not active_subscription:
                await self.platform.send_message(
                    chat_id,
                    "🚫 You don't have an active subscription for this service. Please visit our website to subscribe."
                )
                return

            # 5. If all checks pass, proceed to the original handler.
            return await fn(self, update, context)
        finally:
            db.close()
    return wrapper

class ChatbotCore:
    """Coordinate messaging, odds feeds and analysis engines."""

    def __init__(
        self,
        platform: BaseMessagingClient,
        feed: OddsFeed,
        analysis_engines: Optional[Sequence[AnalysisEngine]] = None,
        openai_api_key: Optional[str] = None,
        model: str = "o4-mini",
        product_id: Optional[str] = None
    ) -> None:
        self.platform = platform
        self.feed = feed
        self.engines: list[AnalysisEngine] = list(analysis_engines or [])
        self.model = model
        self.product_id = product_id or Config.PRODUCT_IDS.first()
        self.openai_api_key = openai_api_key or Config.OPENAI_API_KEY
        if self.openai_api_key:
            self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
        else:
            self.openai_client = None
        logger.debug("ChatbotCore initialized with %d analysis engines", len(self.engines))

    def add_engine(self, engine: AnalysisEngine) -> None:
        self.engines.append(engine)
        logger.debug("Added analysis engine: %s", engine.__class__.__name__)

    def fetch_and_process_events(self) -> None:
        """Fetch upcoming events and process them with all engines."""
        events = self.feed.get_events_in_next_hours(24)
        logger.info("Fetched %d upcoming events", len(events))
        for event in events:
            for engine in self.engines:
                try:
                    engine.process_odds_for_event(event)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Error processing event with %s", engine.__class__.__name__)

    # ------------------------------------------------------------------
    # OpenAI helpers
    # ------------------------------------------------------------------
    def _openai_functions(self):
        return [
            {
                "name": "best_picks",
                "description": "Return top arbitrage opportunities in the next X hours",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "default": 24}
                    }
                },
            },
            {
                "name": "build_parlay",
                "description": "Build a high-value parlay with N legs over the next X hours",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "legs":  {"type": "integer", "default": 4},
                        "hours": {"type": "integer", "default": 24},
                    }
                },
            },
        ]

    def ask_question(self, question: str) -> str:
        system = (
            "You are a sports-betting assistant. "
            "For requests like “high value lines” or “best bets”, use the best_picks function. "
            "For parlays, use the build_parlay function."
        )
        resp = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role":"system",  "content":system},
                {"role":"user",    "content":question},
            ],
            functions=self._openai_functions(),
            function_call="auto",
        )
        msg = resp.choices[0].message

        # if it chose a function, dispatch
        if hasattr(msg, "function_call") and msg.function_call:
            # Access as object properties, not dictionary keys
            name = msg.function_call.name
            args = json.loads(msg.function_call.arguments or "{}")
            
            if name == "best_picks":
                return self._generate_best_picks(hours=args.get("hours",24))
            if name == "build_parlay":
                return self._generate_parlay(
                    legs=args.get("legs",4), hours=args.get("hours",24)
                )
        # otherwise just return the LLM text
        return msg.content.strip() if msg.content else ""
    
    def _generate_best_picks(self, hours: int) -> str:
        evs = self.feed.get_events_in_next_hours(hours)
        lines = []
        for ev in evs:
            for engine in self.engines:
                # This is where you invoke your engine
                df = engine.process_odds_for_event(ev)
                top = df.sort_values("arb_profit_margin", ascending=False).head(1)
                for _, r in top.iterrows():
                    lines.append(
                        f"*{r.outcome_description}* `{r.arb_profit_margin:.2%}`\n"
                        f"{r.over_link} | {r.under_link}"
                    )
        return "\n\n".join(lines) or "No arbitrage found."

    def _generate_parlay(self, legs: int, hours: int) -> str:
        evs = self.feed.get_events_in_next_hours(hours)[:legs]
        picks = []
        for ev in evs:
            for engine in self.engines:
                df = engine.process_odds_for_event(ev)
                best = df.sort_values("sum_prob").iloc[0]
                picks.append(f"{best.outcome_description}: {best.over_odds or best.under_odds}")
        return "Your parlay:\n" + "\n".join(picks)

    def explain_line(self, line_desc: str) -> str:
        """Ask OpenAI to explain a betting line."""
        prompt = f"Explain the following betting line in simple terms: {line_desc}"
        if not self.openai_api_key:
            logger.warning("OpenAI API key not configured")
            return "OpenAI API key not configured."
        resp = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        if not resp.choices:
            logger.warning("OpenAI API returned an empty choices array for line description: %s", line_desc)
            return "I'm sorry, I couldn't generate an explanation for the given line."
        explanation = resp.choices[0].message.content.strip()
        logger.debug("OpenAI explanation: %s", explanation)
        return explanation

    # ------------------------------------------------------------------
    # Messaging integration
    # ------------------------------------------------------------------

    @require_subscription
    async def _handle_ask(self, update, context) -> None:  # pragma: no cover - Telegram interface
        question = " ".join(getattr(context, "args", []) or [])
        if not question:
            await self.platform.send_message(update.effective_chat.id, "Please provide a question after /ask")
            return
        answer = self.ask_question(question)
        await self.platform.send_message(update.effective_chat.id, answer)

    @require_subscription
    async def _handle_explain(self, update, context) -> None:  # pragma: no cover - Telegram interface
        desc = " ".join(getattr(context, "args", []) or [])
        if not desc:
            await self.platform.send_message(update.effective_chat.id, "Provide a line description after /explain")
            return
        explanation = self.explain_line(desc)
        await self.platform.send_message(update.effective_chat.id, explanation)
    
    @require_subscription
    async def _handle_message(self, update, context) -> None:
        """Handle general messages."""
        text = update.message.text.strip() or ""
        if text.startswith("/"):
            return
        answer = self.ask_question(text)
        await self.platform.send_message(update.effective_chat.id, answer)

    def start(self) -> None:
        """Register handlers and start the messaging platform."""
        # self.platform.register_command_handler("ask", self._handle_ask)
        # self.platform.register_command_handler("explain", self._handle_explain)
        self.platform.register_message_handler(lambda msg: True, self._handle_message)
        self.platform.start()
