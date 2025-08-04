import argparse
from config import Config
# from messaging.telegram.bot import TelegramBot
from database import init_db
from feeds.the_odds_api import TheOddsAPI
from analysis.odds_processor import OddsProcessor
from chatbot.core import ChatbotCore
from messaging.mock_client.bot import MockMessagingClient
from messaging.imessage.bot import iMessageBot 
import os

from messaging.telegram.bot import TelegramBot

def main():
    # telegram_bot = TelegramBot(token=Config.TELEGRAM_BOT_TOKEN)
    # iMessage_bot = iMessageBot()

    parser = argparse.ArgumentParser(description="Run the Betting Assistant Chatbot")
    parser.add_argument(
        '--mode',
        type=str,
        choices=['live', 'test'],
        default='test',
        help="Mode to run the chatbot in: 'live' for production or 'test' for local development."
    )
    parser.add_argument(
        '--platform',
        type=str,
        choices=['telegram', 'imessage', 'mock'],
        default='mock',
        help="Platform to run the chatbot on: 'telegram' for Telegram, 'imessage' for iMessage, or 'mock' for a cli client."
    )

    args = parser.parse_args()

    # platform = None
    # product_id = None

    if args.mode == 'test':
        print("[INFO] Running in test mode. Using mock client and test product ID.")
        product_id = Config.PRODUCT_IDS['betting_assistant']['test']  # Use test product ID
    elif args.mode == 'live':
        print("[INFO] Running in live mode. Using real client and live product ID.")
        product_id = Config.PRODUCT_IDS['betting_assistant']['live']

    if args.platform == 'telegram':
        platform = TelegramBot(token=Config.TELEGRAM_BOT_TOKEN)
    elif args.platform == 'imessage':
        platform = iMessageBot()
    else:
        print("[INFO] Running with mock messaging client.")
        # Use the mock client for testing purposes
        platform = MockMessagingClient()

    if not platform or not product_id:
        print("[ERROR] Platform or mode not configured correctly. Exiting.")
        return
    
    init_db()  # Ensure database is initialized before starting the chatbot

    feed = TheOddsAPI()
    todays_events = feed.get_events_between_hours(6, 24)
    engines = [OddsProcessor(todays_events)]
    core = ChatbotCore(
      platform=platform,
      feed=feed,
      analysis_engines=engines,
      openai_api_key=Config.OPENAI_API_KEY,
      model=Config.OPENAI_MODEL,
      product_id=product_id
    )
    core.start()

if __name__=="__main__":
    main()