#################################################################
# Random utility functions that can be accessed throughout
#################################################################

import datetime
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