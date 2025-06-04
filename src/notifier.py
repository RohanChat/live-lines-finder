import requests
import logging # Added for logging
from config import Config # Corrected import path
from telegram import Bot
from telegram.error import BadRequest, Forbidden # Added for error handling
from sqlalchemy.exc import SQLAlchemyError # Added for specific DB error handling

from src.database import get_db_session, User # Added for database interaction

# Setup logger
logger = logging.getLogger(__name__)

class Notifier:
    def __init__(self):
        self.config = Config()
        self.message = ""

    def notify(self, message):
        raise NotImplementedError("Subclasses should implement this method")
    
    def format_message(self, df):
        """
        Format the DataFrame into a Markdown message.
        """
        if df.empty:
            return "No data available."
        
        message = "### Today's NBA Events\n\n"
        for index, row in df.iterrows():
            message += f"- **{row['event_name']}**: {row['start_time']} - {row['status']}\n"
            message += f"  - Odds: {row['odds']}\n"
            message += f"  - Links: {row['links']}\n\n"

        self.message = message
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

        db_session_gen = get_db_session()
        db = next(db_session_gen)
        users_notified_count = 0
        try:
            users = db.query(User).filter(User.phone_number.isnot(None)).all() # Send only to users who provided phone
            if not users:
                logger.info("No registered users with phone numbers found to notify.")
                return

            logger.info(f"Attempting to send notification to {len(users)} user(s).")
            for user in users:
                if user.chat_id:
                    try:
                        self.bot.send_message(
                            chat_id=user.chat_id,
                            text=text_to_send,
                            parse_mode='Markdown'
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
