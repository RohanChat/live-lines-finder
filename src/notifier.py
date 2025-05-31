import requests
from config import Config
from telegram import Bot

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
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.bot = Bot(self.botToken)

    def notify(self, message=None):
        if message is not None:
            self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
        else:
            self.bot.send_message(
                chat_id=self.chat_id,
                text=self.message,
                parse_mode='Markdown'
            )