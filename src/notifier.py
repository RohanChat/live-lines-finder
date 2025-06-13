import requests
import logging # Added for logging
from config import Config # Corrected import path
from telegram import Bot
from telegram.error import BadRequest, Forbidden # Added for error handling
from sqlalchemy.exc import SQLAlchemyError # Added for specific DB error handling
import pandas as pd
import asyncio

from database import get_db_session, User # Added for database interaction

# Setup logger
logger = logging.getLogger(__name__)

class Notifier:
    def __init__(self, include_arbitrage=True, include_mispriced=True):
        self.config = Config()
        self.message = ""
        self.include_arbitrage = include_arbitrage
        self.include_mispriced = include_mispriced

    def get_subscribers(self, db):
        """
        Fetch all users who have provided a phone number and are subscribed.
        """
        try:
            return db.query(User).filter(User.phone_number.isnot(None), User.is_subscribed.is_(True)).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error while fetching subscribers: {e}", exc_info=True)
            return []

    def notify(self, message):
        raise NotImplementedError("Subclasses should implement this method")
    
    def process_dfs(self, *dfs):
        """
        process the first half of the dataframes as arbitrage messages, and the second half as mispriced messages.
        """
        if not dfs:
            logger.warning("No DataFrames provided for processing.")
            return
        
        mid_index = len(dfs) // 2
        arbitrage_dfs = dfs[:mid_index]
        mispriced_dfs = dfs[mid_index:]

        arbitrage_message = ""
        mispriced_message = ""
        
        if self.include_arbitrage and arbitrage_dfs:
            arbitrage_message = self.format_arbitrage_message(arbitrage_dfs[0])
        
        if self.include_mispriced and mispriced_dfs:
            mispriced_message = self.format_mispriced_message(mispriced_dfs[0])

        self.message = f"{arbitrage_message}\n\n{mispriced_message}".strip()
        logger.info("Processed DataFrames into messages.")
        
    

    def format_mispriced_message(self, df):
        """
        Format the DataFrame into a message using Telegram markdown.
        """
        if df.empty:
            return ""
        
        message = "*LATEST MISPRICED / +EV LINES:*\n\n"
        for index, row in df.iterrows():
            # Extract and clean data
            outcome_desc = str(row.get('outcome_description', 'Unknown Event'))
            market_key = str(row.get('market_key', 'Unknown Market'))
            
            # Handle point values (convert arrays to single values)
            point = row.get('point', 'N/A')
            if isinstance(point, (list, tuple)) and len(point) > 0:
                point = point[0]
            point = str(point)
            
            side = str(row.get('side', 'Unknown'))
            bookmaker = str(row.get('bookmaker', 'Unknown'))
            odds = str(row.get('odds', 'N/A'))
            
            # Handle edge/expected value
            edge = row.get('edge', 0)
            if edge and edge != 0:
                edge_pct = f"+{edge * 100:.1f}%" if isinstance(edge, (int, float)) else str(edge)
            else:
                edge_pct = "N/A"
            
            # Handle links
            links = row.get('links', row.get('link', 'N/A'))
            if isinstance(links, (list, tuple)):
                links = ', '.join(str(link) for link in links if link)
            links = str(links) if links else 'N/A'
            
            message += f"• *{outcome_desc}* - {market_key}\n"
            message += f"  {side} {point} @ {odds} ({bookmaker})\n"
            if edge_pct != "N/A":
                message += f"  *Edge:* {edge_pct}\n"
            if links != 'N/A':
                message += f"  *Links:* {links}\n"
            message += "\n"

        return message
    
    def format_arbitrage_message(self, df):
        """
        Format the DataFrame into a message using Telegram markdown.
        """
        if df.empty:
            return ""
        
        message = "*LATEST ARBITRAGE OPPORTUNITIES:*\n\n"
        for index, row in df.iterrows():
            # Extract arbitrage-specific data
            outcome_desc = str(row.get('outcome_description', 'Unknown Event'))
            market_key = str(row.get('market_key', 'Unknown Market'))
            
            # Handle over/under points (convert arrays to single values)
            over_point = row.get('over_point', 'N/A')
            if isinstance(over_point, (list, tuple)) and len(over_point) > 0:
                over_point = over_point[0]
            over_point = str(over_point)
            
            under_point = row.get('under_point', 'N/A')
            if isinstance(under_point, (list, tuple)) and len(under_point) > 0:
                under_point = under_point[0]
            under_point = str(under_point)
            
            # Bookmaker and odds info
            over_bookmaker = str(row.get('over_bookmaker', 'Unknown'))
            under_bookmaker = str(row.get('under_bookmaker', 'Unknown'))
            over_odds = str(row.get('over_odds', 'N/A'))
            under_odds = str(row.get('under_odds', 'N/A'))
            
            # Calculate profit margin if available
            sum_prob = row.get('sum_prob', 0)
            if sum_prob and sum_prob > 0:
                profit_margin = f"{(1/sum_prob - 1) * 100:.2f}%"
            else:
                profit_margin = "N/A"
            
            # Handle links
            links = row.get('links', row.get('link', 'N/A'))
            if isinstance(links, (list, tuple)):
                links = ', '.join(str(link) for link in links if link)
            links = str(links) if links else 'N/A'
            
            message += f"• *{outcome_desc}* - {market_key}\n"
            message += f"  Over {over_point} @ {over_odds} ({over_bookmaker})\n"
            message += f"  Under {under_point} @ {under_odds} ({under_bookmaker})\n"
            if profit_margin != "N/A":
                message += f"  *Profit:* {profit_margin}\n"
            if links != 'N/A':
                message += f"  *Links:* {links}\n"
            message += "\n"
        
        return message

    def get_config(self):
        return self.config
    
class TelegramNotifier(Notifier):
    def __init__(self, include_arbitrage=True, include_mispriced=True):
        super().__init__(include_arbitrage, include_mispriced)
        self.botToken = Config.TELEGRAM_BOT_TOKEN
        # self.chat_id = Config.TELEGRAM_CHAT_ID # Removed as chat_id is now dynamic
        if not self.botToken:
            logger.error("TELEGRAM_BOT_TOKEN not configured. TelegramNotifier will not work.")
            self.bot = None
        else:
            self.bot = Bot(self.botToken)

    def notify(self, message=None):
        if not self.bot:
            logger.error("Telegram bot not initialized. Cannot send notifications.")
            return

        text_to_send = message if message is not None else self.message
        if not text_to_send:
            logger.warning("No message content to send.")
            return

        # Run the async method in a new event loop
        asyncio.run(self._send_notifications_async(text_to_send))

    async def _send_notifications_async(self, text_to_send):
        db_session_gen = get_db_session()
        db = next(db_session_gen)
        users_notified_count = 0
        try:
            users = self.get_subscribers(db)
            logger.debug(f"Fetched {len(users)} users from the database for notification.")
            if not users:
                logger.info("No registered users with phone numbers and valid subscriptions found to notify.")
                return

            logger.info(f"Attempting to send notification to {len(users)} user(s).")
            for user in users:
                if user.chat_id:
                    try:
                        await self.bot.send_message(
                            chat_id=user.chat_id,
                            text=text_to_send,
                            parse_mode='Markdown'  # Enable Markdown parsing for bold text
                        )
                        users_notified_count += 1
                        logger.debug(f"Notification sent to user_id: {user.id}, chat_id: {user.chat_id}")
                    except BadRequest as e:
                        logger.error(f"Failed to send message to chat_id {user.chat_id} (user_id: {user.id}): {e}. Chat not found or other issue.", exc_info=True)
                    except Forbidden as e:
                        logger.warning(f"Bot blocked by user or kicked from chat_id {user.chat_id} (user_id: {user.id}): {e}. Consider removing user or marking as inactive.", exc_info=True)
                    except Exception as e:
                        logger.error(f"An unexpected error occurred while sending message to chat_id {user.chat_id} (user_id: {user.id}): {e}", exc_info=True)
                else:
                    logger.warning(f"User_id {user.id} has no chat_id associated. Skipping.")

            if users_notified_count > 0:
                logger.info(f"Notification successfully sent to {users_notified_count} user(s).")
            else:
                logger.info("Notification was not sent to any users (possibly due to errors or no valid users).")

        except SQLAlchemyError as e:
            logger.error(f"Database error while querying users: {e}", exc_info=True)
            # Gracefully exit the method as we can't fetch users
            return
        except Exception as e: # Catch any other non-SQLAlchemy errors during the DB part
            logger.error(f"Unexpected error during database interaction phase: {e}", exc_info=True)
            return
        finally:
            db.close()
            logger.debug("Database session closed.")
