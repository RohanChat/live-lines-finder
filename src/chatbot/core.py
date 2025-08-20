from __future__ import annotations

from functools import wraps
import json
import os
import logging
from datetime import datetime, timedelta, UTC
from typing import Iterable, Sequence, Dict, Any, Optional, List

import openai

from config.config import Config
from src.database import get_db_session
from src.database.models import UserSubscription
from src.database.session import get_user_by_phone
from src.messaging.base import BaseMessagingClient
from src.feeds.base import OddsFeed
from src.feeds.api.the_odds_api import TheOddsApiAdapter
from src.feeds.api.unabated_api import UnabatedApiAdapter
from src.feeds.api.oddspapi_api import OddsPapiApiAdapter
from src.feeds.models import SportKey, MarketKey, EventOdds
from src.chatbot.handlers import get_best_bets
from src.analysis.base import AnalysisEngine
from src.feeds.query import FeedQuery

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
        provider_name: str = Config.ODDS_PROVIDER,
        analysis_engines: Optional[Sequence[AnalysisEngine]] = None,
        openai_api_key: Optional[str] = None,
        model: str = Config.OPENAI_MODEL,
        product_id: Optional[str] = None
    ) -> None:
        self.platform = platform
        self.provider_name = provider_name
        self.feed = self.create_feed_adapter(provider_name)
        self.engines: list[AnalysisEngine] = list(analysis_engines or [])
        self.model = model
        self.product_id = product_id or Config.PRODUCT_IDS.get('betting_assistant', {}).get('test', 'default')
        self.openai_api_key = openai_api_key or Config.OPENAI_API_KEY
        if self.openai_api_key:
            self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
        else:
            self.openai_client = None
        # Responses API conversation tracking (simple)
        self.conversations: Dict[str, str] = {}  # chat_id -> conversation_id
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
    def _openai_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "best_picks",
                    "description": "Return top arbitrage opportunities in the next X hours",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "hours": {"type": "integer", "default": 24}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "build_parlay",
                    "description": "Build a high-value parlay with N legs over the next X hours",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "legs": {"type": "integer", "default": 4},
                            "hours": {"type": "integer", "default": 24}
                        }
                    }
                }
            }
        ]

    def ask_question(self, question: str, chat_id: Optional[str] = None) -> str:
        """Ask a question with conversation context."""
        chat_id = chat_id or "default"
        
        if not self.openai_client:
            # Fallback to smart odds if no AI
            try:
                return self.get_smart_odds(question)
            except Exception as e:
                return f"Error: {e}"
        
        # Get odds context if relevant
        odds_context = ""
        try:
            if any(word in question.lower() for word in ["odds", "picks", "bets", "spread", "total", "moneyline"]):
                odds_context = self.get_smart_odds(question)
        except Exception as e:
            logger.warning(f"Failed to get odds context: {e}")
        
        # Prepare input with context
        full_question = f"{question}\n\nOdds Context:\n{odds_context}" if odds_context else question
        
        # Simple conversation history management
        if not hasattr(self, '_manual_history'):
            self._manual_history = {}
        if chat_id not in self._manual_history:
            self._manual_history[chat_id] = []
        
        # Add current question to history
        self._manual_history[chat_id].append({"role": "user", "content": full_question})
        
        # Keep only last 10 messages for context
        messages = self._manual_history[chat_id][-10:]
        
        try:
            # Use Chat Completions API with conversation history
            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self._openai_tools(),
                tool_choice="auto"
            )
            
            # Handle response
            message = response.choices[0].message
            
            # Handle tool calls
            if message.tool_calls:
                result = self._handle_tool_calls(message.tool_calls)
                self._manual_history[chat_id].append({"role": "assistant", "content": result})
                return result
            
            content = message.content.strip() if message.content else "No response generated."
            self._manual_history[chat_id].append({"role": "assistant", "content": content})
            return content
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            # Fallback to odds context if available
            return odds_context or f"Error: {e}"

    def _handle_tool_calls(self, tool_calls):
        """Handle tool calls from OpenAI response."""
        for tool_call in tool_calls:
            function = tool_call.function
            if function.name == "best_picks":
                try:
                    args = json.loads(function.arguments or "{}")
                    return self.get_smart_odds("best picks", hours=args.get("hours", 24))
                except Exception as e:
                    logger.error(f"Error in best_picks tool: {e}")
                    return f"Error getting best picks: {e}"
            elif function.name == "build_parlay":
                return "Sorry, parlay building is not yet supported with the new feed system."
        
        return "Tool call completed"

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
        chat_id = str(update.effective_chat.id)
        answer = self.ask_question(question, chat_id=chat_id)
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
        chat_id = str(update.effective_chat.id)
        answer = self.ask_question(text, chat_id=chat_id)
        await self.platform.send_message(update.effective_chat.id, answer)

    def reset_conversation(self, chat_id: str):
        """Reset conversation context for a specific chat."""
        self.conversations.pop(chat_id, None)
        if hasattr(self, '_manual_history'):
            self._manual_history.pop(chat_id, None)
        logger.info(f"Reset conversation for chat_id: {chat_id}")

    # ------------------------------------------------------------------
    # AI-Powered Smart Query Building
    # ------------------------------------------------------------------
    
    def _analyze_query_with_ai(self, question: str) -> Dict[str, Any]:
        """
        Use AI to comprehensively analyze a user query and extract all betting intent.
        Returns structured data about sports, teams, players, markets, timing, etc.
        """
        if not self.openai_client:
            logger.warning("OpenAI client not available, falling back to basic parsing")
            return self._fallback_query_analysis(question)
        
        try:
            system_prompt = """You are an expert sports betting query analyzer. Extract ALL relevant information from user queries about sports betting.

Return a JSON object with these fields:
{
  "sports": ["NBA", "NFL", "MLB", "NHL", "NCAAF", "NCAAB", "WNBA", "MMA"],
  "teams": ["team names mentioned"],
  "players": ["player names mentioned"], 
  "markets": ["H2H", "SPREAD", "TOTAL", "PLAYER_POINTS", "PLAYER_ASSISTS", "PLAYER_REBOUNDS"],
  "timeframe": {
    "type": "tonight|today|tomorrow|weekend|week|specific_date|general",
    "hours": 24,
    "description": "human readable time description"
  },
  "intent": "general_picks|team_specific|player_props|market_specific|analysis",
  "confidence": 0.95
}

Examples:
- "Lakers odds tonight" -> sports:["NBA"], teams:["Lakers"], timeframe:{type:"tonight",hours:8}
- "LeBron points props" -> sports:["NBA"], players:["LeBron James"], markets:["PLAYER_POINTS"]
- "best NFL bets this weekend" -> sports:["NFL"], timeframe:{type:"weekend",hours:72}
- "Mahomes passing yards tomorrow" -> sports:["NFL"], players:["Patrick Mahomes"], markets:["PLAYER_POINTS"]
- "Knicks spread" -> sports:["NBA"], teams:["New York Knicks"], markets:["SPREAD"]

Be intelligent about team name variations (Lakers=Los Angeles Lakers, Knicks=New York Knicks, etc.)
For player props, infer the sport from the player name.
Extract timeframe even from implicit references."""

            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Analyze this betting query: {question}"}
                ]
            )
            
            content = response.choices[0].message.content.strip()
            analysis = json.loads(content)
            
            logger.info(f"AI query analysis for '{question}': {analysis}")
            return analysis
            
        except Exception as e:
            logger.warning(f"AI query analysis failed: {e}, falling back to basic parsing")
            return self._fallback_query_analysis(question)
    
    def _fallback_query_analysis(self, question: str) -> Dict[str, Any]:
        """Fallback analysis when AI is unavailable."""
        question_lower = question.lower()
        
        # Basic sport detection
        sports = []
        if any(word in question_lower for word in ["nba", "basketball", "lakers", "warriors"]):
            sports.append("NBA")
        if any(word in question_lower for word in ["nfl", "football", "chiefs", "patriots"]):
            sports.append("NFL")
        if any(word in question_lower for word in ["mlb", "baseball", "yankees", "dodgers"]):
            sports.append("MLB")
        if any(word in question_lower for word in ["nhl", "hockey", "rangers", "bruins"]):
            sports.append("NHL")
        
        # Basic time detection
        timeframe = {"type": "general", "hours": 24, "description": "next 24 hours"}
        if "tonight" in question_lower:
            timeframe = {"type": "tonight", "hours": 8, "description": "tonight"}
        elif "tomorrow" in question_lower:
            timeframe = {"type": "tomorrow", "hours": 24, "description": "tomorrow"}
        elif "weekend" in question_lower:
            timeframe = {"type": "weekend", "hours": 72, "description": "this weekend"}
        
        return {
            "sports": sports,
            "teams": [],
            "players": [],
            "markets": ["H2H", "SPREAD", "TOTAL"],
            "timeframe": timeframe,
            "intent": "general_picks",
            "confidence": 0.5
        }
    
    def _sports_to_leagues(self, sports: List[SportKey]) -> List[str]:
        """
        Convert SportKey enums to league strings that Unabated expects.
        Uses the mapping from unabated_maps.json.
        """
        if isinstance(self.feed, UnabatedApiAdapter):
            leagues = []
            for sport in sports:
                # Map SportKey to league string using reverse lookup
                for league, sport_key in self.feed.SPORT_MAP.items():
                    if sport_key == sport.value:
                        leagues.append(league)
                        break
            return leagues
        else:
            # For other feeds, the sport enum values might work directly
            return [sport.value for sport in sports]
    
    def build_smart_query(self, question: str, hours: int = 24) -> FeedQuery:
        """
        Parse a user question using AI and build an appropriate FeedQuery.
        Handles all scenarios: time-based, player props, team-specific, etc.
        """
        # Get comprehensive AI analysis
        analysis = self._analyze_query_with_ai(question)
        
        # Convert sports strings to SportKey enums
        detected_sports = []
        sport_mapping = {
            "NFL": SportKey.NFL, "NBA": SportKey.NBA, "MLB": SportKey.MLB, "NHL": SportKey.NHL,
            "NCAAF": SportKey.NCAAF, "NCAAB": SportKey.NCAAB, "WNBA": SportKey.WNBA, "MMA": SportKey.MMA
        }
        
        for sport_str in analysis.get("sports", []):
            if sport_str in sport_mapping:
                detected_sports.append(sport_mapping[sport_str])
        
        # If no sports detected, use all available sports
        if not detected_sports:
            detected_sports = self.feed.list_sports()
        
        # Convert sports to leagues for the feed
        leagues = self._sports_to_leagues(detected_sports)
        
        # Convert market strings to MarketKey enums
        detected_markets = []
        market_mapping = {
            "H2H": MarketKey.H2H, "SPREAD": MarketKey.SPREAD, "TOTAL": MarketKey.TOTAL,
            "TEAM_TOTAL": MarketKey.TEAM_TOTAL, "PLAYER_POINTS": MarketKey.PLAYER_POINTS,
            "PLAYER_ASSISTS": MarketKey.PLAYER_ASSISTS, "PLAYER_REBOUNDS": MarketKey.PLAYER_REBOUNDS
        }
        
        for market_str in analysis.get("markets", []):
            if market_str in market_mapping:
                detected_markets.append(market_mapping[market_str])
        
        # If no markets detected, use main game markets
        if not detected_markets:
            detected_markets = [MarketKey.H2H, MarketKey.SPREAD, MarketKey.TOTAL]
        
        # Use AI-detected timeframe or default
        timeframe = analysis.get("timeframe", {})
        query_hours = timeframe.get("hours") or hours  # Handle None case
        
        # Build time range
        end_time = datetime.now(UTC) + timedelta(hours=query_hours)
        
        # Store analysis for later use in filtering
        query = FeedQuery(
            leagues=leagues,
            markets=detected_markets,
            start_time_to=end_time
        )
        
        # Store AI analysis in query for later filtering
        query._ai_analysis = analysis
        
        logger.info(f"Built AI-powered query from '{question}': "
                   f"sports={[s.value for s in detected_sports]}, "
                   f"markets={[m.value for m in detected_markets]}, "
                   f"hours={query_hours}, "
                   f"teams={analysis.get('teams', [])}, "
                   f"players={analysis.get('players', [])}")
        
        return query

    def start(self) -> None:
        """Register handlers and start the messaging platform."""
        # self.platform.register_command_handler("ask", self._handle_ask)
        # self.platform.register_command_handler("explain", self._handle_explain)
        self.platform.register_message_handler(lambda msg: True, self._handle_message)
        self.platform.start()

    def get_smart_odds(self, question: str, hours: int = 24) -> str:
        """
        Unified method to get odds based on a natural language question.
        Now with comprehensive AI-powered analysis and filtering.
        """
        try:
            # Build the query from the question (now fully AI-powered)
            query = self.build_smart_query(question, hours)
            analysis = getattr(query, '_ai_analysis', {})
            
            # Fetch odds using the query
            logger.info(f"Fetching odds with AI-powered query: leagues={query.leagues}, markets={[m.value for m in query.markets]}")
            event_odds_list = self.feed.get_odds(query)
            
            if not event_odds_list:
                timeframe_desc = analysis.get("timeframe", {}).get("description", f"next {hours} hours")
                return f"No upcoming games found matching your request for {timeframe_desc}."
            
            # Apply AI-powered filtering
            filtered_odds = self._apply_ai_filters(event_odds_list, analysis)
            
            if not filtered_odds:
                teams = analysis.get("teams", [])
                players = analysis.get("players", [])
                if teams or players:
                    filter_desc = f"teams: {', '.join(teams)}" if teams else f"players: {', '.join(players)}"
                    return f"Found {len(event_odds_list)} games but none matching {filter_desc}"
                else:
                    filtered_odds = event_odds_list
            
            return self._format_odds_response(filtered_odds, question, analysis, limit=5)
            
        except Exception as e:
            logger.error(f"Error in get_smart_odds: {e}")
            return f"Sorry, I couldn't fetch odds right now. Error: {e}"
    
    def _apply_ai_filters(self, event_odds_list: List[EventOdds], analysis: Dict[str, Any]) -> List[EventOdds]:
        """
        Apply intelligent filtering based on AI analysis of the user query.
        Handles teams, players, and specific market preferences.
        """
        filtered_odds = event_odds_list
        
        # Filter by teams if specified
        teams = analysis.get("teams", [])
        if teams:
            filtered_odds = self._filter_odds_by_teams_ai(filtered_odds, teams)
            logger.info(f"Filtered by teams {teams}: {len(filtered_odds)} games remaining")
        
        # Filter by players if specified (for player props)
        players = analysis.get("players", [])
        if players:
            filtered_odds = self._filter_odds_by_players(filtered_odds, players)
            logger.info(f"Filtered by players {players}: {len(filtered_odds)} games remaining")
        
        return filtered_odds
    
    def _filter_odds_by_teams_ai(self, event_odds_list: List[EventOdds], team_names: List[str]) -> List[EventOdds]:
        """
        Filter odds using AI-detected team names.
        Much more flexible than keyword matching.
        """
        if not team_names:
            return event_odds_list
        
        filtered = []
        
        for event_odds in event_odds_list:
            competitor_names = [comp.name.lower() for comp in event_odds.event.competitors]
            
            # Check if any AI-detected team matches any competitor
            for team_name in team_names:
                team_lower = team_name.lower()
                
                # Direct match or partial match
                if any(team_lower in comp_name or comp_name in team_lower 
                       for comp_name in competitor_names):
                    filtered.append(event_odds)
                    break
                
                # Handle common abbreviations and variations
                # The AI should have already normalized these, but add some safety
                team_variations = self._get_team_variations(team_name)
                if any(var in comp_name for var in team_variations 
                       for comp_name in competitor_names):
                    filtered.append(event_odds)
                    break
        
        return filtered
    
    def _get_team_variations(self, team_name: str) -> List[str]:
        """Get common variations of a team name for matching."""
        variations = [team_name.lower()]
        
        # Common abbreviations
        abbrev_map = {
            "lakers": ["lal", "los angeles"],
            "warriors": ["gsw", "golden state"],
            "knicks": ["nyk", "new york"],
            "nets": ["bkn", "brooklyn"],
            "celtics": ["bos", "boston"],
            "heat": ["mia", "miami"],
            # Add more as needed
        }
        
        for full_name, abbrevs in abbrev_map.items():
            if full_name in team_name.lower():
                variations.extend(abbrevs)
        
        return variations
    
    def _filter_odds_by_players(self, event_odds_list: List[EventOdds], player_names: List[str]) -> List[EventOdds]:
        """
        Filter for games involving specific players.
        This would need roster data or player-team mapping.
        For now, we'll return games and let the market filtering handle player props.
        """
        # TODO: Implement player-to-team mapping for better filtering
        # For now, return all games as player props are market-specific
        logger.info(f"Player filtering not yet implemented for: {player_names}")
        return event_odds_list
    
    def _extract_team_names(self, question: str) -> List[str]:
        """
        Extract specific team names mentioned in the question.
        Uses enhanced keyword detection with comprehensive team lists.
        """
        return self._extract_team_names_keywords(question)
    
    def _extract_team_names_keywords(self, question: str) -> List[str]:
        """Enhanced keyword-based team extraction with comprehensive team lists."""
        question_lower = question.lower()
        
        # Comprehensive team keywords across all major sports
        team_keywords = [
            # NBA teams
            "lakers", "warriors", "celtics", "nets", "knicks", "76ers", "sixers", "raptors",
            "bucks", "cavaliers", "cavs", "bulls", "pistons", "pacers", "heat", "hawks", 
            "hornets", "wizards", "magic", "clippers", "kings", "suns", "nuggets", 
            "timberwolves", "thunder", "blazers", "jazz", "mavericks", "mavs", "rockets", 
            "grizzlies", "pelicans", "spurs",
            
            # NFL teams
            "patriots", "bills", "dolphins", "jets", "steelers", "ravens", "browns", "bengals",
            "titans", "colts", "texans", "jaguars", "chiefs", "chargers", "broncos", "raiders",
            "cowboys", "giants", "eagles", "commanders", "packers", "bears", "lions", "vikings",
            "falcons", "panthers", "saints", "buccaneers", "bucs", "49ers", "seahawks", "rams", "cardinals",
            
            # MLB teams  
            "yankees", "red sox", "orioles", "rays", "blue jays", "guardians", "twins", "white sox",
            "tigers", "royals", "astros", "angels", "mariners", "rangers", "athletics", "braves",
            "mets", "phillies", "nationals", "marlins", "brewers", "cardinals", "reds", "cubs",
            "pirates", "dodgers", "padres", "giants", "rockies", "diamondbacks",
            
            # NHL teams
            "bruins", "sabres", "red wings", "panthers", "canadiens", "senators", "lightning",
            "maple leafs", "hurricanes", "blue jackets", "devils", "islanders", "rangers",
            "flyers", "penguins", "capitals", "blackhawks", "avalanche", "stars", "wild",
            "predators", "blues", "jets", "coyotes", "ducks", "flames", "oilers", "kings",
            "sharks", "kraken", "canucks", "golden knights"
        ]
        
        found_teams = []
        for team in team_keywords:
            if team in question_lower:
                found_teams.append(team)
        
        return found_teams
    
    def _filter_odds_by_teams(self, event_odds_list: List[EventOdds], team_names: List[str]) -> List[EventOdds]:
        """Filter odds to only include games involving the specified teams."""
        filtered = []
        
        for event_odds in event_odds_list:
            competitor_names = [comp.name.lower() for comp in event_odds.event.competitors]
            
            for team_name in team_names:
                if any(team_name in comp_name for comp_name in competitor_names):
                    filtered.append(event_odds)
                    break
        
        return filtered
    
    def _format_odds_response(self, event_odds_list: List[EventOdds], original_question: str, analysis: Dict[str, Any], limit: int = 5) -> str:
        """Format the odds response for display to the user with AI context."""
        limited_odds = event_odds_list[:limit]
        
        lines = []
        
        # Create contextual header based on AI analysis
        intent = analysis.get("intent", "general_picks")
        timeframe_desc = analysis.get("timeframe", {}).get("description", "upcoming")
        teams = analysis.get("teams", [])
        players = analysis.get("players", [])
        
        if players:
            lines.append(f"🎯 Found {len(event_odds_list)} games with player props for {', '.join(players)} ({timeframe_desc}):")
        elif teams:
            lines.append(f"🎯 Found {len(event_odds_list)} games involving {', '.join(teams)} ({timeframe_desc}):")
        else:
            lines.append(f"🎯 Found {len(event_odds_list)} {timeframe_desc} games:")
        
        for i, event_odds in enumerate(limited_odds, 1):
            event = event_odds.event
            
            home_team = next((c.name for c in event.competitors if c.role == 'home'), 'TBD')
            away_team = next((c.name for c in event.competitors if c.role == 'away'), 'TBD')
            
            # Format game time if available
            game_time = ""
            if hasattr(event, 'commence_time') and event.commence_time:
                game_time = f" - {event.commence_time.strftime('%I:%M %p')}"
            
            lines.append(f"\n{i}. **{away_team} @ {home_team}**{game_time}")
            
            for market in event_odds.markets:
                market_name = market.market_key.value.upper()
                lines.append(f"   📊 {market_name}:")
                
                outcomes_by_book = {}
                for outcome in market.outcomes:
                    book = outcome.bookmaker_key or "Unknown"
                    if book not in outcomes_by_book:
                        outcomes_by_book[book] = []
                    outcomes_by_book[book].append(outcome)
                
                for book_count, (book, outcomes) in enumerate(outcomes_by_book.items()):
                    if book_count >= 2:  # Limit to 2 bookmakers
                        break
                        
                    outcome_strs = []
                    for outcome in outcomes:
                        price_str = f"{outcome.price_american:+}" if outcome.price_american else "N/A"
                        if outcome.line:
                            outcome_strs.append(f"{outcome.outcome_key} {outcome.line} ({price_str})")
                        else:
                            outcome_strs.append(f"{outcome.outcome_key} ({price_str})")
                    
                    if outcome_strs:
                        lines.append(f"     • {book}: {' | '.join(outcome_strs)}")
        
        if len(event_odds_list) > limit:
            lines.append(f"\n... and {len(event_odds_list) - limit} more games")
        
        # Add confidence indicator if AI analysis has low confidence
        confidence = analysis.get("confidence", 1.0)
        if confidence < 0.7:
            lines.append(f"\n💡 Note: Query interpretation confidence: {confidence:.0%}")
        
        return "\n".join(lines)
