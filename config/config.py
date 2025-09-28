import os, json
from pathlib import Path
from dotenv import load_dotenv

# --- dotenv loading ---
ENV = os.getenv("ENV", "local")
DOTENV_PATH = os.getenv("DOTENV_PATH")
if ENV == "local":
    load_dotenv()  # local only
elif DOTENV_PATH:
    # prod/staging: secret-mounted .env; let it override if pre-set
    load_dotenv(dotenv_path=DOTENV_PATH, override=False)

# Base dir for resolving relative paths
BASE_DIR = Path(__file__).resolve().parent.parent

class Config:
    """Configuration class for the application."""

    # Database
    LOCAL_DATABASE_URL = 'sqlite:///./chatbot.db'
    DATABASE_URL = os.getenv('DATABASE_URL_POSTGRES', LOCAL_DATABASE_URL)

    # Simple env vars
    ODDS_API_KEY = os.getenv('ODDS_API_KEY')
    ODDS_API_URL = os.getenv('ODDS_API_URL')
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
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
    MOCK_CHAT_ID = os.getenv('MOCK_CHAT_ID')
    ACTIVE_ODDS_PROVIDERS = ["theoddsapi"]
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    WEB_APP_API_KEY = os.getenv('WEB_APP_API_KEY')

    # Stripe
    STRIPE_SECRET_KEY_LIVE = os.getenv('STRIPE_SECRET_KEY_LIVE')
    STRIPE_SECRET_KEY_TEST = os.getenv('STRIPE_SECRET_KEY_TEST')
    STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET_TEST = os.getenv('STRIPE_WEBHOOK_SECRET_TEST')
    STRIPE_WEBHOOK_SECRET_LIVE = os.getenv('STRIPE_WEBHOOK_SECRET_LIVE')
    STRIPE_SUBSCRIPTION_PRICE_ID = os.getenv('STRIPE_SUBSCRIPTION_PRICE_ID')

    # ----- System prompt (guarded absolute/relative) -----
    _system_prompt_path_str = os.getenv('SYSTEM_PROMPT_PATH')
    SYSTEM_PROMPT_PATH = None
    if _system_prompt_path_str:
        p = Path(_system_prompt_path_str.strip("'\""))
        SYSTEM_PROMPT_PATH = p if p.is_absolute() else (BASE_DIR / p)

    SYSTEM_PROMPT = ""
    if SYSTEM_PROMPT_PATH and SYSTEM_PROMPT_PATH.exists():
        with open(SYSTEM_PROMPT_PATH, 'r', encoding='utf-8') as f:
            SYSTEM_PROMPT = f.read()
    else:
        print(f"WARNING: System prompt file not found or path not set. Looked at: {SYSTEM_PROMPT_PATH}")

    # ----- TOA mapping (guarded absolute/relative) -----
    _toa_mapping_path_str = os.getenv('TOA_MAPPING_PATH')
    TOA_MAPPING_PATH = None
    if _toa_mapping_path_str:
        p = Path(_toa_mapping_path_str.strip("'\""))
        TOA_MAPPING_PATH = p if p.is_absolute() else (BASE_DIR / p)

    TOA_MAPPING = {}
    if TOA_MAPPING_PATH and TOA_MAPPING_PATH.exists():
        with open(TOA_MAPPING_PATH, 'r', encoding='utf-8') as f:
            TOA_MAPPING = json.load(f)
    else:
        print(f"WARNING: TOA mapping file not found or path not set. Looked at: {TOA_MAPPING_PATH}")

    # Stripe product info
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
