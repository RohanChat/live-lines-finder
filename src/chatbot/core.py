from __future__ import annotations

import os
import logging
from typing import Iterable, Sequence, Dict, Any, Optional

import openai

from messaging.base import BaseMessagingClient
from feeds.base import OddsFeed
from analysis.base import AnalysisEngine

logger = logging.getLogger(__name__)


class ChatbotCore:
    """Coordinate messaging, odds feeds and analysis engines."""

    def __init__(
        self,
        platform: BaseMessagingClient,
        feed: OddsFeed,
        analysis_engines: Optional[Sequence[AnalysisEngine]] = None,
        openai_api_key: Optional[str] = None,
        model: str = "o4-mini",
    ) -> None:
        self.platform = platform
        self.feed = feed
        self.engines: list[AnalysisEngine] = list(analysis_engines or [])
        self.model = model
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
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
                    engine.process_event(event)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Error processing event with %s", engine.__class__.__name__)

    # ------------------------------------------------------------------
    # OpenAI helpers
    # ------------------------------------------------------------------
    def ask_question(self, question: str) -> str:
        """Return an answer from OpenAI for the given question."""
        if not self.openai_api_key:
            logger.warning("OpenAI API key not configured")
            return "OpenAI API key not configured."
        if not self.openai_client:
            logger.warning("OpenAI client not initialized")
            return "OpenAI client not initialized."
        resp = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": question}],
        )
        if not resp.choices:
            logger.warning("OpenAI API returned an empty choices list")
            return "OpenAI did not generate a response."
        answer = resp.choices[0].message["content"].strip()
        logger.debug("OpenAI answer: %s", answer)
        return answer

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
        explanation = resp.choices[0].message["content"].strip()
        logger.debug("OpenAI explanation: %s", explanation)
        return explanation

    # ------------------------------------------------------------------
    # Messaging integration
    # ------------------------------------------------------------------
    async def _handle_ask(self, update, context) -> None:  # pragma: no cover - Telegram interface
        question = " ".join(getattr(context, "args", []) or [])
        if not question:
            await self.platform.send_message(update.effective_chat.id, "Please provide a question after /ask")
            return
        answer = self.ask_question(question)
        await self.platform.send_message(update.effective_chat.id, answer)

    async def _handle_explain(self, update, context) -> None:  # pragma: no cover - Telegram interface
        desc = " ".join(getattr(context, "args", []) or [])
        if not desc:
            await self.platform.send_message(update.effective_chat.id, "Provide a line description after /explain")
            return
        explanation = self.explain_line(desc)
        await self.platform.send_message(update.effective_chat.id, explanation)

    def start(self) -> None:
        """Register handlers and start the messaging platform."""
        self.platform.register_command_handler("ask", self._handle_ask)
        self.platform.register_command_handler("explain", self._handle_explain)
        self.platform.start()
