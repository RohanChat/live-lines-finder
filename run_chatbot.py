import argparse
from config.config import Config
from src.feeds.models import SportKey
from src.database import init_db
from src.feeds.api.the_odds_api import TheOddsApiAdapter as TheOddsAPI
from src.chatbot.core import ChatbotCore
from src.messaging.mock_client.bot import MockMessagingClient
from src.messaging.imessage.bot import iMessageBot 
from src.feeds.query import FeedQuery
import os
import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# from src.messaging.telegram.bot import TelegramBot

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
    parser.add_argument(
        '--chat_id',
        type=str,
        default=Config.MOCK_CHAT_ID,
        help="Set a chat id: ONLY FOR TESTING PURPOSES. This will be used by the mock client to simulate a chat environment."
    )
    parser.add_argument(
        '--feeds',
        type=str,
        nargs='+',
        default=Config.ACTIVE_ODDS_PROVIDERS,
        help="List of odds feeds to use (space-separated)."
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
        if args.chat_id:
            print("YOU CAN ONLY SET A CHAT ID WHEN USING THE MOCK CLIENT. THIS WILL BE IGNORED.")
        platform = TelegramBot(token=Config.TELEGRAM_BOT_TOKEN)
    elif args.platform == 'imessage':
        if args.chat_id:
            print("YOU CAN ONLY SET A CHAT ID WHEN USING THE MOCK CLIENT. THIS WILL BE IGNORED.")
        platform = iMessageBot()
    elif args.platform == 'mock':
        print("[INFO] Running with mock messaging client.")
        # Use the mock client for testing purposes
        platform = MockMessagingClient(chat_id=args.chat_id)

    if args.feeds:
        print(f"[INFO] Using the following odds feeds: {', '.join(args.feeds)}")
        feeds = args.feeds
    else:
        print("[WARNING] No odds feeds specified. Using default feeds.")
        feeds = Config.ACTIVE_ODDS_PROVIDERS

    if not platform or not product_id:
        print("[ERROR] Platform or mode not configured correctly. Exiting.")
        return
    
    init_db()  # Ensure database is initialized before starting the chatbot

    core = ChatbotCore(
      platform=platform,
      provider_names=feeds,
      openai_api_key=Config.OPENAI_API_KEY,
      model=Config.OPENAI_MODEL,
      product_id=product_id
    )
    core.start()

if __name__=="__main__":
    main()