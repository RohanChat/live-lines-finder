import sys
import pytest
sys.path.append('src')

from stripe_service import StripeService

pytest.skip("Stripe integration test", allow_module_level=True)

# Test with a phone number
phone = "+447914699809"  # Replace with a real phone from your Stripe account
print(f"Testing phone: {phone}")

result = StripeService.find_customer_by_phone(phone)
customer_id, is_active, end_date = result

print(f"Customer ID: {customer_id}")
print(f"Is Active: {is_active}")
print(f"End Date: {end_date}")