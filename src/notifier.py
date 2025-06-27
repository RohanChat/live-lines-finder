import requests
import logging # Added for logging
from config import Config # Corrected import path
from telegram import Bot
from telegram.error import BadRequest, Forbidden # Added for error handling
from sqlalchemy.exc import SQLAlchemyError # Added for specific DB error handling
import pandas as pd
import asyncio
import threading
import concurrent.futures

from database import get_db_session, User # Added for database interaction

# Setup logger
logger = logging.getLogger(__name__)

class Notifier:
    def __init__(self, include_arbitrage=True, include_mispriced=True, links_only=True):
        self.config = Config()
        self.message = ""
        self.include_arbitrage = include_arbitrage
        self.include_mispriced = include_mispriced
        self.links_only = links_only

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
        Format the DataFrame into a plain text message for Telegram.
        """
        if df.empty:
            return ""
        
        message = "🔥 LATEST MISPRICED / +EV LINES 🔥\n\n"
        for index, row in df.iterrows():
            print("CHECKING FOR LINKS RIGHT NOW - Mispriced")
            
            # Extract and clean data
            outcome_desc = str(row.get('outcome_description', 'Unknown Event'))
            market_key = str(row.get('market_key', 'Unknown Market'))
            
            # Handle point values (convert arrays to single values)
            point = row.get('point', 'N/A')
            if isinstance(point, (list, tuple, pd.Series)) and len(point) > 0:
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
            
            # Handle links - try multiple possible column names
            links = None
            for link_col in ['links', 'link', 'url', 'urls', 'sportsbook_links']:
                if link_col in row.index:
                    potential_links = row[link_col]
                    # Check if it's not null/nan
                    if potential_links is not None and not (isinstance(potential_links, float) and pd.isna(potential_links)):
                        links = potential_links
                        break
            
            print(f"DEBUG - Links found: {links} (type: {type(links)})")
            
            if isinstance(links, (list, tuple)):
                links_list = [str(link) for link in links if link and str(link) != 'nan']
                links_str = ', '.join(links_list) if links_list else 'N/A'
            elif links and not pd.isna(links):
                links_str = str(links)
            else:
                links_str = 'N/A'
            
            # Build message with plain text formatting
            message += f"💰 {outcome_desc} - {market_key}\n"
            message += f"   {side} {point} @ {odds} ({bookmaker})\n"
            if edge_pct != "N/A":
                message += f"   Edge: {edge_pct}\n"
            if links_str != 'N/A' and links_str.strip():
                message += f"   Links: {links_str}\n"
            message += "\n"

        return message
    
    def format_arbitrage_message(self, df):
        """
        Format the DataFrame into a plain text message for Telegram.
        """
        if df.empty:
            return ""
        
        # Filter for links_only mode if enabled
        if self.links_only:
            print(f"DEBUG - links_only mode enabled. Original arbitrage rows: {len(df)}")
            print(f"DEBUG - Columns in DataFrame: {df.columns.tolist()}")
            
            # Check if the expected columns exist
            if 'over_link' in df.columns and 'under_link' in df.columns:
                # Debug: show sample values
                print(f"DEBUG - Sample over_link values: {df['over_link'].head(3).tolist()}")
                print(f"DEBUG - Sample under_link values: {df['under_link'].head(3).tolist()}")
                
                # More robust filtering - handle various empty/null representations
                mask = (
                    df['over_link'].notna() & 
                    df['under_link'].notna() &
                    (df['over_link'].astype(str) != '') & 
                    (df['under_link'].astype(str) != '') &
                    (df['over_link'].astype(str) != 'None') &
                    (df['under_link'].astype(str) != 'None') &
                    (df['over_link'].astype(str) != 'nan')  &
                    (df['under_link'].astype(str) != 'nan')
                )
                
                print(f"DEBUG - Mask evaluation: {mask.sum()} rows pass filter out of {len(df)}")
                df = df[mask]
                
                if df.empty:
                    logger.info("No arbitrage opportunities with both over and under links found after filtering.")
                    return ""
                else:
                    print(f"DEBUG - After filtering: {len(df)} rows remain")
            else:
                print(f"DEBUG - Expected columns 'over_link' and 'under_link' not found in DataFrame")
                print(f"DEBUG - Available columns: {df.columns.tolist()}")
                # Don't filter if columns don't exist - this might be a different data structure
        
        message = "⚡ LATEST ARBITRAGE OPPORTUNITIES ⚡\n\n"
        for index, row in df.iterrows():
            print("CHECKING FOR ARBITRAGE LINKS - Processing row", index)
            
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
            
            # Handle links - arbitrage has separate over_link and under_link columns
            links = None
            over_link = row.get('over_link', None)
            under_link = row.get('under_link', None)
            
            # Try to get combined links first, then fall back to separate links
            for link_col in ['links', 'link', 'url', 'urls', 'sportsbook_links']:
                if link_col in row.index:
                    potential_links = row[link_col]
                    # Check if it's not null/nan
                    if potential_links is not None and not (isinstance(potential_links, float) and pd.isna(potential_links)):
                        links = potential_links
                        break
            
            # If no combined links, create from over_link and under_link
            if not links:
                link_parts = []
                if over_link and not pd.isna(over_link) and str(over_link) != 'None':
                    link_parts.append(f"Over: {str(over_link)}")
                if under_link and not pd.isna(under_link) and str(under_link) != 'None':
                    link_parts.append(f"Under: {str(under_link)}")
                
                if link_parts:
                    links = ' | '.join(link_parts)
            
            print(f"DEBUG - Arbitrage links found: {links} (over: {over_link}, under: {under_link})")
            
            if isinstance(links, (list, tuple)):
                links_list = [str(link) for link in links if link and str(link) != 'nan']
                links_str = ', '.join(links_list) if links_list else 'N/A'
            elif links and not pd.isna(links):
                links_str = str(links)
            else:
                links_str = 'N/A'
            
            print(f"DEBUG - Arbitrage links after processing: {links_str}")
            
            # Build message with plain text formatting
            message += f"🔥 {outcome_desc} - {market_key}\n"
            message += f"   Over {over_point} @ {over_odds} ({over_bookmaker})\n"
            message += f"   Under {under_point} @ {under_odds} ({under_bookmaker})\n"
            if profit_margin != "N/A":
                message += f"   Profit: {profit_margin}\n"
            if links_str != 'N/A' and links_str.strip():
                message += f"   Links: {links_str}\n"
            message += "\n"
        
        return message

    def get_config(self):
        return self.config
    
class TelegramNotifier(Notifier):
    def __init__(self, include_arbitrage=True, include_mispriced=True, links_only=True):
        super().__init__(include_arbitrage, include_mispriced, links_only)
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

        # Run the async method in a separate thread to avoid event loop conflicts
        def run_async_in_thread():
            """Run the async notification in a separate thread with its own event loop."""
            try:
                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Run the async function
                    loop.run_until_complete(self._send_notifications_async(text_to_send))
                finally:
                    loop.close()
            except Exception as e:
                logger.error(f"Error in notification thread: {e}", exc_info=True)

        # Execute in a separate thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_async_in_thread)
            try:
                # Wait for completion with a timeout
                future.result(timeout=30)  # 30 second timeout
                logger.debug("Notification thread completed successfully")
            except concurrent.futures.TimeoutError:
                logger.error("Notification sending timed out after 30 seconds")
            except Exception as e:
                logger.error(f"Error in notification thread execution: {e}", exc_info=True)

    async def notify_async(self, message=None):
        """Async version of notify for use in async contexts."""
        if not self.bot:
            logger.error("Telegram bot not initialized. Cannot send notifications.")
            return

        text_to_send = message if message is not None else self.message
        if not text_to_send:
            logger.warning("No message content to send.")
            return

        # Directly call the async method since we're already in an async context
        await self._send_notifications_async(text_to_send)

    async def _send_notifications_async(self, text_to_send):
        # Limit message length to prevent Telegram errors
        max_length = 4000  # Telegram's limit is 4096, leave some buffer
        if len(text_to_send) > max_length:
            text_to_send = text_to_send[:max_length] + "\n\n... (message truncated)"
            logger.warning(f"Message truncated to {max_length} characters to fit Telegram limits.")
        
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
