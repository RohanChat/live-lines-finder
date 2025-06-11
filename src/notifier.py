import requests
import logging # Added for logging
from config import Config # Corrected import path
from telegram import Bot
from telegram.error import BadRequest, Forbidden # Added for error handling
from sqlalchemy.exc import SQLAlchemyError # Added for specific DB error handling
import pandas as pd
import asyncio

from src.database import get_db_session, User # Added for database interaction

# Setup logger
logger = logging.getLogger(__name__)

class Notifier:
    def __init__(self):
        self.config = Config()
        self.message = ""

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

        arbitrage_message = self.format_arbitrage_message(arbitrage_dfs[0]) if arbitrage_dfs else ""
        mispriced_message = self.format_mispriced_message(mispriced_dfs[0]) if mispriced_dfs else ""

        self.message = f"{arbitrage_message}\n\n{mispriced_message}"
        logger.info("Processed DataFrames into messages.")
        
    

    def format_mispriced_message(self, df):
        """
        Format the DataFrame into a safe text message without complex Markdown.
        """
        if df.empty:
            return ""
        
        message = "LATEST MISPRICED / +EV LINES:\n\n"
        for index, row in df.iterrows():
            # Use simple formatting to avoid Markdown parsing issues
            event_name = str(row.get('event_name', 'Unknown Event'))
            start_time = str(row.get('start_time', 'TBD'))
            status = str(row.get('status', 'Unknown'))
            odds = str(row.get('odds', 'N/A'))
            links = str(row.get('links', 'N/A'))
            
            message += f"• {event_name}: {start_time} - {status}\n"
            message += f"  Odds: {odds}\n"
            message += f"  Links: {links}\n\n"

        return message
    
    def format_arbitrage_message(self, df):
        """
        Format the DataFrame into a safe text message without complex Markdown.
        """
        if df.empty:
            return ""
        
        message = "LATEST ARBITRAGE OPPORTUNITIES:\n\n"
        for index, row in df.iterrows():
            # Use simple formatting to avoid Markdown parsing issues
            event_name = str(row.get('event_name', 'Unknown Event'))
            start_time = str(row.get('start_time', 'TBD'))
            status = str(row.get('status', 'Unknown'))
            odds = str(row.get('odds', 'N/A'))
            links = str(row.get('links', 'N/A'))
            
            message += f"• {event_name}: {start_time} - {status}\n"
            message += f"  Odds: {odds}\n"
            message += f"  Links: {links}\n\n"
        
        return message

    def get_config(self):
        return self.config
    
class TelegramNotifier(Notifier):
    def __init__(self):
        super().__init__()
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
                            parse_mode=None  # Disable Markdown parsing to avoid formatting issues
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
