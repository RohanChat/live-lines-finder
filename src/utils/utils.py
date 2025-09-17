#################################################################
# Random utility functions that can be accessed throughout
#################################################################

import datetime
import logging
from pathlib import Path
import re
from typing import Optional

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