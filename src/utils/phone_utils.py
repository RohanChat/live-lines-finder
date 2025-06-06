import re

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
