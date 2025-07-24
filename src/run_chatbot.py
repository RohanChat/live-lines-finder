from config import Config
from messaging.telegram import TelegramBot
from feeds.the_odds_api import TheOddsAPI
from analysis.odds_processor import OddsProcessor
from chatbot.core import ChatbotCore
import os

def main():
    bot = TelegramBot(token=Config.TELEGRAM_BOT_TOKEN)
    feed = TheOddsAPI()
    engines = [OddsProcessor()]
    core = ChatbotCore(
      platform=bot,
      feed=feed,
      analysis_engines=engines,
      openai_api_key=Config.OPENAI_API_KEY,
      model=Config.OPENAI_MODEL,
    )
    core.start()

if __name__=="__main__":
    main()