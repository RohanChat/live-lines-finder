#################################################################
# Random utility functions that can be accessed throughout
#################################################################

import datetime
from functools import wraps
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import List, Optional, get_origin, get_args
import logging

import redis

from config.config import Config
from src.database.models import UserSubscription
from src.database.session import get_db_session, get_user_by_phone
logger = logging.getLogger(__name__)

def standardize_phone_number(phone_number: str) -> str:
    """
    Standardize phone number by removing all non-digit characters except the leading +
    
    Examples:
    "+1 (555) 123-4567" -> "+15551234567"
    "1-555-123-4567" -> "+15551234567"
    "(555) 123 4567" -> "+5551234567"
    "555.123.4567" -> "+5551234567"
    """
    if not phone_number:
        return ""
    
    # Remove all non-digit characters except +
    cleaned = re.sub(r'[^\d+]', '', phone_number.strip())
    
    # If it doesn't start with +, add it
    if not cleaned.startswith('+'):
        cleaned = '+' + cleaned
    
    return cleaned

def get_phone_variations(phone_number: str) -> list[str]:
    """
    Get different variations of a phone number for searching
    
    Returns:
    - Original standardized format: "+15551234567"
    - Without plus: "15551234567"
    - With country code assumed if missing
    """
    standardized = standardize_phone_number(phone_number)
    
    variations = [
        standardized,  # "+15551234567"
        standardized[1:] if standardized.startswith('+') else standardized,  # "15551234567"
    ]
    
    # Remove duplicates while preserving order
    return list(dict.fromkeys(variations))

def implied_probability(decimal_odds):
        """Convert Decimal odds to implied probability."""
        return 1 / decimal_odds

def american_to_decimal(american_odds):
    """Convert American odds to Decimal odds."""
    if american_odds < 0:
        return (100 / abs(american_odds)) + 1
    else:
        return (american_odds / 100) + 1
        
def decimal_to_american(decimal_odds):
    if decimal_odds >= 2:
            # For positive odds: (d - 1) * 100
        return (decimal_odds - 1) * 100
    else:
            # For negative odds: -100 / (d - 1)
        return -100 / (decimal_odds - 1)
    
def _iso_utc_z(dt: Optional[datetime.datetime]) -> Optional[str]:
    """Serialize datetimes as ISO-8601 in UTC with trailing 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")

def init_logging():
    """Initialize console + file logging exactly once with absolute path.
    Ensures all modules inheriting from root get the file handler.
    """
    root_logger = logging.getLogger()
    if not root_logger.handlers:  # Only configure if nothing configured yet
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    try:
        project_root = Path(__file__).resolve().parent
        log_dir = project_root / 'logs'
        log_dir.mkdir(exist_ok=True)
        datetime_now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        logfile = log_dir / f'chatbot_{datetime_now}.log'
        if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', '') == str(logfile) for h in root_logger.handlers):
            fh = logging.FileHandler(logfile, mode='a', encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            root_logger.addHandler(fh)
            root_logger.info('[logging] File handler attached -> %s', logfile)
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to initialize file logging: %s', e)

_redis_client = None
def get_redis_client():
    """
    Returns a singleton Redis client instance.
    Reads the REDIS_URL from the application config.
    """
    global _redis_client
    if _redis_client is None:
        if not Config.REDIS_URL:
            logger.warning("REDIS_URL not configured. Caching will be disabled.")
            return None
        try:
            # The `from_url` method is the standard way to connect.
            # decode_responses=True makes it return strings instead of bytes.
            _redis_client = redis.from_url(Config.REDIS_URL, decode_responses=True)
            _redis_client.ping()
            logger.info("Successfully connected to Redis.")
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}. Caching will be disabled.")
            _redis_client = None # Ensure it remains None on failure
    return _redis_client

def _generate_cache_key(prefix: str, *args, **kwargs) -> str:
    """
    Creates a stable, canonical cache key from function arguments.
    It specifically handles Pydantic models (like FeedQuery) by creating a
    sorted, deterministic representation of their data.
    """
    # Find a Pydantic model object in the arguments, which is our primary target.
    query_obj = None
    for arg in args:
        if hasattr(arg, 'model_dump'): # Duck-typing for Pydantic models
            query_obj = arg
            break
    if not query_obj and 'q' in kwargs:
        query_obj = kwargs['q']

    if query_obj:
        # Create a canonical representation of the query object.
        query_dict = query_obj.model_dump(exclude_none=True)
        # Sort lists to ensure that the order of items doesn't change the cache key.
        # e.g., markets=['h2h', 'total'] should have the same key as markets=['total', 'h2h']
        for key, value in query_dict.items():
            if isinstance(value, list):
                try:
                    # We sort the string representation to handle un-sortable types like dicts.
                    query_dict[key] = sorted(map(str, value))
                except TypeError:
                    pass # If sorting fails for any reason, proceed with the original order.
        
        # Use a hash of the sorted JSON string for a clean, fixed-length key.
        canonical_str = json.dumps(query_dict, sort_keys=True)
        hash_id = hashlib.md5(canonical_str.encode()).hexdigest()
        return f"{prefix}:{hash_id}"

    # Fallback for functions that don't use a Pydantic model as a primary argument.
    # This is less robust but provides a basic caching mechanism.
    key_str = f"{args}-{kwargs}"
    hash_id = hashlib.md5(key_str.encode()).hexdigest()
    return f"{prefix}:{hash_id}"

def redis_cache(prefix: str, ttl: int = 300):
    """
    A decorator to cache the results of a function in Redis.
    It now automatically handles Pydantic model hydration and dehydration.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            redis_client = get_redis_client()
            # Get the return type hint from the decorated function (e.g., List[Event])
            return_type = func.__annotations__.get('return')

            if not redis_client:
                # If Redis is down, just call the function directly.
                return func(*args, **kwargs)

            cache_key = _generate_cache_key(prefix, *args, **kwargs)
            
            try:
                cached_result_str = redis_client.get(cache_key)
                if cached_result_str:
                    logger.debug(f"CACHE HIT for key: {cache_key}")
                    cached_data = json.loads(cached_result_str)
                    
                    # --- START NEW RE-HYDRATION LOGIC ---
                    if return_type and hasattr(return_type, 'model_validate'):
                        # Case 1: The return type is a single Pydantic model (e.g., -> EventOdds)
                        return return_type.model_validate(cached_data)
                    
                    origin = get_origin(return_type)
                    if origin in (list, List) and return_type.__args__:
                        # Case 2: The return type is a List of Pydantic models (e.g., -> List[Event])
                        model_class = return_type.__args__[0]
                        if hasattr(model_class, 'model_validate'):
                            return [model_class.model_validate(item) for item in cached_data]
                    # --- END NEW RE-HYDRATION LOGIC ---

                    # Fallback: If no Pydantic model found, return the raw dict/list
                    return cached_data
            except Exception as e:
                logger.error(f"Redis GET or re-hydration failed for key {cache_key}: {e}")

            logger.debug(f"CACHE MISS for key: {cache_key}")
            # Execute the actual function to get the fresh Pydantic objects
            result = func(*args, **kwargs)
            
            try:
                # --- START NEW DEHYDRATION LOGIC ---
                # Convert Pydantic object(s) to dict(s) before storing
                if isinstance(result, list):
                    data_to_store = [item.model_dump() for item in result]
                elif hasattr(result, 'model_dump'):
                    data_to_store = result.model_dump()
                else:
                    data_to_store = result
                # --- END NEW DEHYDRATION LOGIC ---

                redis_client.set(cache_key, json.dumps(data_to_store), ex=ttl)
            except Exception as e:
                logger.error(f"Redis SET or dehydration failed for key {cache_key}: {e}")

            return result
        return wrapper
    return decorator

class SubscriptionError(Exception):
    """Custom exception raised when a user lacks an active subscription."""
    pass

def require_subscription(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        # This logic to find the user_id from phone number is now in _handle_message
        # The decorator now expects a clean user_id
        user_id = kwargs.get("user_id")
        if not user_id and len(args) > 1:
            user_id = args[1] # Assumes user_id is the first argument after `self`

        if not user_id:
            # This should ideally not happen if called correctly
            raise SubscriptionError("User identification failed.")

        db_session = next(get_db_session())
        try:
            subscription = db_session.query(UserSubscription).filter(
                UserSubscription.user_id == user_id, 
                UserSubscription.active == True
            ).first()

            if not subscription:
                logger.info(f"Subscription check failed for user_id: {user_id}")
                # --- FIX: Raise our specific, catchable exception ---
                raise SubscriptionError("Active subscription required to use this feature. Please visit https://buy.stripe.com/bJefZi6Nlav46bl7xz2cg01 to subscribe.")
            
            logger.debug(f"Subscription check passed for user_id: {user_id}. Welcome!")
            # If subscription is valid, call the original function
            return fn(self, *args, **kwargs)
        finally:
            db_session.close()
    return wrapper