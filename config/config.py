import os, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

class Config:
    """Configuration class for the application."""

    LOCAL_DATABASE_URL = 'sqlite:///./chatbot.db'
    DATABASE_URL = os.getenv('DATABASE_URL_POSTGRES', LOCAL_DATABASE_URL)
    ODDS_API_KEY = os.getenv('ODDS_API_KEY')
    ODDS_API_URL = os.getenv('ODDS_API_URL')
    TOA_MAPPING_PATH = Path(os.getenv('TOA_MAPPING_PATH', './config/mappings/theoddsapi_mappings.json'))
    with open(TOA_MAPPING_PATH, 'r') as f:
        TOA_MAPPING = json.load(f)
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    SUPABASE_SERVICE_ROLE_KEY = os.getenv('SERVICE_ROLE_KEY')
    SHARPSPORTS_API_KEY = os.getenv('SHARPSPORTS_API_KEY')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'o4-mini')
    ODDSPAPI_WSS_URL = os.getenv('ODDSPAPI_WSS_URL')
    ODDSPAPI_CLIENT_NAME = os.getenv('ODDSPAPI_CLIENT_NAME')
    ODDSPAPI_CLIENT_API_KEY = os.getenv('ODDSPAPI_CLIENT_API_KEY')
    BOLTODDS_TOKEN = os.getenv('BOLTODDS_API_KEY') 
    UNABATED_API_KEY = os.getenv('UNABATED_API_KEY')  
    UNABATED_REALTIME_API_HOST = os.getenv('UNABATED_REALTIME_API_HOST')
    UNABATED_REALTIME_API_REGION = os.getenv('UNABATED_REALTIME_API_REGION')
    UNABATED_DATA_API_URL = os.getenv('UNABATED_DATA_API_URL')
    MOCK_CHAT_ID = os.getenv('MOCK_CHAT_ID')  # Default mock chat ID
    ACTIVE_ODDS_PROVIDERS = ["unabated", "theoddsapi"]
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    WEB_APP_API_KEY = os.getenv('WEB_APP_API_KEY')  # Default API key for web app
    
    # Stripe Configuration
    STRIPE_SECRET_KEY_LIVE = os.getenv('STRIPE_SECRET_KEY_LIVE')
    STRIPE_SECRET_KEY_TEST = os.getenv('STRIPE_SECRET_KEY_TEST')
    STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET_TEST = os.getenv('STRIPE_WEBHOOK_SECRET_TEST')
    STRIPE_WEBHOOK_SECRET_LIVE = os.getenv('STRIPE_WEBHOOK_SECRET_LIVE')
    STRIPE_SUBSCRIPTION_PRICE_ID = os.getenv('STRIPE_SUBSCRIPTION_PRICE_ID')

    # Path to the system prompt text file
    SYSTEM_PROMPT_PATH = os.getenv('SYSTEM_PROMPT_PATH', './config/prompts/system_prompt.txt')
    with open(SYSTEM_PROMPT_PATH, 'r') as f:
        SYSTEM_PROMPT = f.read()
        
    # keys for the different products and their product ids from stripe
    PRODUCTS = {
        'betting_assistant': {
            'live': {
                'product_id': os.getenv('BETTING_ASSISTANT_STRIPE_PRODUCT_ID'),
                'payment_url': os.getenv('BETTING_ASSISTANT_STRIPE_PAYMENT_URL_LIVE')
            },
            'test': {
                'product_id': os.getenv('TEST_PRODUCT_ID'),
                'payment_url': os.getenv('TEST_PRODUCT_PAYMENT_URL')
            }
        }
    }