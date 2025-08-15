from __future__ import annotations

from functools import wraps
import json
import os
import logging
from typing import Iterable, Sequence, Dict, Any, Optional

import openai

from config.config import Config
from src.database import get_db_session
from src.database.models import UserSubscription
from src.database.session import get_user_by_phone
from src.messaging.base import BaseMessagingClient
from src.feeds.base import OddsFeed, SgpSupport
from src.feeds.api.the_odds_api import TheOddsApiAdapter
from src.feeds.api.unabated_api import UnabatedApiAdapter
from src.feeds.api.oddspapi_api import OddsPapiApiAdapter
from src.feeds.query import FeedQuery
from src.feeds.api.unabated_sgp import UnabatedSgpAdapter
from src.feeds.models import SportKey, MarketKey, SgpQuoteRequest, SgpLeg
from src.chatbot.handlers import get_best_bets
from src.analysis.base import AnalysisEngine
from src.utils.mappings import map_sport_name_to_key

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
        analysis_engines: Optional[Sequence[AnalysisEngine]] = None,
        openai_api_key: Optional[str] = None,
        model: str = "o4-mini",
        product_id: Optional[str] = None
    ) -> None:
        self.platform = platform
        provider_name = Config.ODDS_PROVIDER
        self.feed = self.create_feed_adapter(provider_name)
        self.engines: list[AnalysisEngine] = list(analysis_engines or [])
        self.model = model
        self.product_id = product_id or Config.PRODUCT_IDS.first()
        self.openai_api_key = openai_api_key or Config.OPENAI_API_KEY
        if self.openai_api_key:
            self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
        else:
            self.openai_client = None
        logger.debug("ChatbotCore initialized with %d analysis engines", len(self.engines))

    def create_feed_adapter(self, name: str) -> OddsFeed:
        if name == "theoddsapi":
            return TheOddsApiAdapter()
        elif name == "unabated":
            return UnabatedApiAdapter()
        elif name == "oddspapi":
            return OddsPapiApiAdapter()
        else:
            raise ValueError(f"Unknown odds provider: {name}")

    def add_engine(self, engine: AnalysisEngine) -> None:
        self.engines.append(engine)
        logger.debug("Added analysis engine: %s", engine.__class__.__name__)

    # ------------------------------------------------------------------
    # OpenAI helpers
    # ------------------------------------------------------------------
    def _openai_functions(self):
        return [
            {
                "name": "best_picks",
                "description": "Return top arbitrage opportunities in the next X hours for a given sport",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sport": {"type": "string", "description": "The sport to get picks for, e.g., 'WNBA', 'NFL', 'Soccer'"},
                        "hours": {"type": "integer", "default": 24}
                    },
                    "required": ["sport"]
                },
            },
            {
                "name": "build_parlay",
                "description": "Build a high-value parlay or Same Game Parlay (SGP).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sport": {"type": "string", "description": "The sport to build the parlay for, e.g., 'NBA', 'NFL'."},
                        "legs": {"type": "integer", "description": "The number of legs for the parlay.", "default": 3},
                        "hours": {"type": "integer", "description": "Timeframe in hours to look for games.", "default": 24},
                        "is_sgp": {"type": "boolean", "description": "Whether this should be a Same Game Parlay (SGP).", "default": False},
                        "markets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of markets to include (e.g., 'h2h', 'spreads', 'player_points')."
                        }
                    },
                    "required": ["sport", "legs"]
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
            
            # This is a simplified mapping for now.
            # A real implementation would need to parse the user's query
            # to determine the sport.
            if name == "best_picks":
                sport_name = args.get("sport")
                if not sport_name:
                    return "Please specify a sport when asking for best picks."

                sport_key = map_sport_name_to_key(sport_name)
                if not sport_key:
                    return f"Sorry, I don't recognize the sport '{sport_name}'. Please try a common name like 'NFL', 'NBA', or 'Soccer'."

                return get_best_bets(
                    feed=self.feed,
                    sport=sport_key,
                    hours=args.get("hours", 24),
                    analysis_engines=self.engines,
                    chatbot=self
                )
            if name == "build_parlay":
                sport_name = args.get("sport")
                num_legs = args.get("legs", 3)
                is_sgp = args.get("is_sgp", False)

                if not sport_name:
                    return "Please specify a sport to build a parlay."

                sport_key = map_sport_name_to_key(sport_name)
                if not sport_key:
                    return f"Sorry, I don't recognize the sport '{sport_name}'."

                if is_sgp:
                    # For SGP, we need a single event. Let's find one.
                    # A real implementation would be more robust here.
                    try:
                        events = self.feed.get_odds(FeedQuery(sport=sport_key, markets=[MarketKey.H2H]))
                        if not events:
                            return f"Couldn't find an upcoming event for {sport_name} to build an SGP."
                        target_event = events[0]

                        # Use Unabated SGP adapter
                        sgp_adapter = UnabatedSgpAdapter()

                        # This is a simplified leg creation. A real implementation would need
                        # to get available markets for the event and map them correctly.
                        # For now, we create some plausible legs as a demo.
                        legs = [
                            SgpLeg(event_id=target_event.event.event_id, market_key=MarketKey.H2H, outcome_key=target_event.event.competitors[0].name),
                            SgpLeg(event_id=target_event.event.event_id, market_key=MarketKey.TOTAL, outcome_key="Over", line=220.5),
                        ]

                        req = SgpQuoteRequest(bookmaker="draftkings", legs=legs[:num_legs])

                        # Get deeplink and price
                        response = sgp_adapter.deeplink_sgp(req)

                        leg_descs = [f"- {l.market_key.value}: {l.outcome_key} {l.line or ''}" for l in req.legs]

                        return (
                            f"Here is a {len(req.legs)}-leg SGP suggestion for the "
                            f"{target_event.event.competitors[0].name} vs {target_event.event.competitors[1].name} game:\n\n"
                            + "\n".join(leg_descs)
                            + f"\n\nClick here to build it: [Bet Slip]({response.deeplink_url})"
                        )

                    except Exception as e:
                        logger.error(f"SGP construction failed: {e}")
                        return "Sorry, I couldn't build a Same Game Parlay right now. This feature is in beta."

                else:
                    # For a standard parlay, we'll just suggest combining top bets.
                    # A more advanced version would ensure legs are from different games.
                    return (
                        "Building multi-game parlays is complex. A great strategy is to combine "
                        "several high-value single bets. You can ask me for 'best bets' for different "
                        "sports and combine them on your favorite sportsbook!"
                    )
        # otherwise just return the LLM text
        return msg.content.strip() if msg.content else ""

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
