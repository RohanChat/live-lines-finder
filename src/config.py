import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    """Configuration class for the application."""

    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./telegram_users.db')
    ODDS_API_KEY = os.getenv('ODDS_API_KEY')
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    SUPABASE_SERVICE_ROLE_KEY = os.getenv('SERVICE_ROLE_KEY')
    SHARPSPORTS_API_KEY = os.getenv('SHARPSPORTS_API_KEY')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'o4-mini')
    ODDSPAPI_WSS_URL = os.getenv('ODDSPAPI_WSS_URL')
    ODDSPAPI_CLIENT_NAME = os.getenv('ODDSPAPI_CLIENT_NAME')
    ODDSPAPI_CLIENT_API_KEY = os.getenv('ODDSPAPI_CLIENT_API_KEY')
    
    # Stripe Configuration
    STRIPE_SECRET_KEY_LIVE = os.getenv('STRIPE_SECRET_KEY_LIVE')
    STRIPE_SECRET_KEY_TEST = os.getenv('STRIPE_SECRET_KEY_TEST')
    STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET_TEST = os.getenv('STRIPE_WEBHOOK_SECRET_TEST')
    STRIPE_WEBHOOK_SECRET_LIVE = os.getenv('STRIPE_WEBHOOK_SECRET_LIVE')
    STRIPE_SUBSCRIPTION_PRICE_ID = os.getenv('STRIPE_SUBSCRIPTION_PRICE_ID')
