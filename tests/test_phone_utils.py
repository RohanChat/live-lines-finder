import sys
sys.path.append('src')

from phone_utils import standardize_phone_number, get_phone_variations

# Test various phone number formats
test_phones = [
    "+1 (555) 123-4567",
    "1-555-123-4567", 
    "(555) 123 4567",
    "555.123.4567",
    "+447914699809",
    "44 7914 699 809",
    "07914 699809",
    "+1 555 123 4567"
]

print("🧪 PHONE NUMBER STANDARDIZATION TEST")
print("="*50)

for phone in test_phones:
    standardized = standardize_phone_number(phone)
    variations = get_phone_variations(phone)
    print(f"Original: {phone}")
    print(f"Standardized: {standardized}")
    print(f"Variations: {variations}")
    print("-" * 30)
