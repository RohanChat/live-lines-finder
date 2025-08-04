from config import Config
# from messaging.telegram.bot import TelegramBot
from database import init_db
from feeds.the_odds_api import TheOddsAPI
from analysis.odds_processor import OddsProcessor
from chatbot.core import ChatbotCore
from messaging.mock_client.bot import MockMessagingClient
from messaging.imessage.bot import iMessageBot 
import os

def main():
    # telegram_bot = TelegramBot(token=Config.TELEGRAM_BOT_TOKEN)
    # iMessage_bot = iMessageBot()
    init_db()  # Ensure database is initialized before starting the chatbot
    mock_client = MockMessagingClient()
    feed = TheOddsAPI()
    todays_events = feed.get_events_between_hours(6, 24)
    engines = [OddsProcessor(todays_events)]
    core = ChatbotCore(
      platform=mock_client,
      feed=feed,
      analysis_engines=engines,
      openai_api_key=Config.OPENAI_API_KEY,
      model=Config.OPENAI_MODEL,
      product_id=Config.PRODUCT_IDS.get('betting_assistant', None)  # Use the product ID from config
    )
    core.start()

if __name__=="__main__":
    main()