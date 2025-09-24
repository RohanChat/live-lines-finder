import stripe
import logging
from config.config import Config
from datetime import datetime
from src.utils.utils import standardize_phone_number, get_phone_variations

logger = logging.getLogger(__name__)

stripe.api_key = Config.STRIPE_SECRET_KEY_LIVE

class StripeService:
    @staticmethod
    def find_customer_by_phone(phone_number: str):
        """
        Find Stripe customer by phone number
        Returns: (customer_id, subscription_active, subscription_end_date) or (None, False, None)
        """
        try:
            # Get standardized phone number and variations
            standardized_phone = standardize_phone_number(phone_number)
            phone_variations = get_phone_variations(phone_number)
            
            logger.info(f"Searching for customer with phone: {phone_number}")
            logger.info(f"Standardized: {standardized_phone}")
            logger.info(f"Variations: {phone_variations}")
            
            # Try each phone variation in both metadata and phone field
            for phone_var in phone_variations:
                # Search in customer metadata first
                customers = stripe.Customer.search(
                    query=f'metadata["phone_number"]:"{phone_var}"',
                    limit=10
                )
                
                if customers.data:
                    customer = customers.data[0]
                    logger.info(f"Found customer {customer.id} via metadata search with {phone_var}")
                    is_active, end_date = StripeService.verify_subscription(customer.id)
                    return customer.id, is_active, end_date
                
                # Search in phone field
                customers = stripe.Customer.search(
                    query=f'phone:"{phone_var}"',
                    limit=10
                )
                
                if customers.data:
                    customer = customers.data[0]
                    logger.info(f"Found customer {customer.id} via phone field search with {phone_var}")
                    is_active, end_date = StripeService.verify_subscription(customer.id)
                    return customer.id, is_active, end_date
            
            logger.info(f"No Stripe customer found with phone number: {phone_number} or its variations")
            return None, False, None
            
        except Exception as e:
            logger.error(f"Error searching for customer by phone {phone_number}: {e}")
            return None, False, None

    @staticmethod
    def create_checkout_session(chat_id: int, phone_number: str = None, user_email: str = None):
        """Create a Stripe checkout session for subscription"""
        try:
            # Standardize phone number if provided
            standardized_phone = standardize_phone_number(phone_number) if phone_number else None
            
            # Create customer with metadata including phone and chat_id
            customer_data = {
                "metadata": {
                    "telegram_chat_id": str(chat_id),
                    "phone_number": standardized_phone or ""
                }
            }
            if user_email:
                customer_data["email"] = user_email
            if standardized_phone:
                customer_data["phone"] = standardized_phone
            
            customer = stripe.Customer.create(**customer_data)
            
            # Create checkout session
            session = stripe.checkout.Session.create(
                customer=customer.id,
                payment_method_types=['card'],
                line_items=[{
                    'price': Config.STRIPE_SUBSCRIPTION_PRICE_ID,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url='https://t.me/your_bot_username?start=success',
                cancel_url='https://t.me/your_bot_username?start=cancel',
                metadata={
                    'telegram_chat_id': str(chat_id),
                    'phone_number': standardized_phone or ""
                }
            )
            
            return session.url, customer.id
            
        except Exception as e:
            logger.error(f"Error creating Stripe checkout session: {e}")
            return None, None

    @staticmethod
    def verify_subscription(customer_id: str):
        """Verify if customer has active subscription"""
        try:
            subscriptions = stripe.Subscription.list(
                customer=customer_id,
                status='active',
                limit=1
            )
            
            if subscriptions.data:
                subscription = subscriptions.data[0]
                # Try to get end date, but don't fail if it doesn't exist
                end_date = None
                if hasattr(subscription, 'current_period_end') and subscription.current_period_end:
                    end_date = datetime.fromtimestamp(subscription.current_period_end)
                
                return True, end_date
            
            return False, None
            
        except Exception as e:
            logger.error(f"Error verifying subscription: {e}")
            return False, None

    @staticmethod
    def link_customer_to_telegram(customer_id: str, chat_id: int):
        """Link existing Stripe customer to Telegram chat_id"""
        try:
            stripe.Customer.modify(
                customer_id,
                metadata={
                    "telegram_chat_id": str(chat_id)
                }
            )
            logger.info(f"Linked Stripe customer {customer_id} to Telegram chat_id {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error linking customer to Telegram: {e}")
            return False