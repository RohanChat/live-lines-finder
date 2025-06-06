import logging
import asyncio # Added for asyncio.run(main())

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from sqlalchemy.exc import SQLAlchemyError # Added for specific DB error handling

from config import Config
from database import get_db_session, User, init_db
from stripe_service import StripeService
from utils.phone_utils import standardize_phone_number

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command with phone number verification."""
    chat_id = update.effective_chat.id
    logger.info(f"Received /start command from chat_id: {chat_id}")

    # Check if user already exists in our database first
    db_session_gen = get_db_session()
    db = next(db_session_gen)
    try:
        user = db.query(User).filter(User.chat_id == chat_id).first()
        
        if user and user.phone_number:
            # User exists with phone number - check Stripe subscription status
            customer_id, is_active, end_date = StripeService.find_customer_by_phone(user.phone_number)
            
            if customer_id and is_active:
                # Update database with Stripe info if needed
                if not user.stripe_customer_id:
                    user.stripe_customer_id = customer_id
                    user.is_subscribed = True
                    user.subscription_end_date = end_date
                    db.commit()
                
                await update.message.reply_text(
                    f"Welcome back! ✅ Your subscription is active.\n\n"
                    "You'll receive live betting line notifications when significant changes occur."
                )
                return
            elif customer_id and not is_active:
                await update.message.reply_text(
                    "Your subscription appears to be inactive or expired. 😞\n\n"
                    "Please visit our website to reactivate your subscription or contact support."
                )
                return
        
        # For new users or existing users without phone verification
        await show_phone_verification_prompt(update, context)
        
    except SQLAlchemyError as e:
        logger.error(f"Database error in start_command for chat_id {chat_id}: {e}", exc_info=True)
        db.rollback()
        await update.message.reply_text("A database error occurred. Please try again later.")
    except Exception as e:
        logger.error(f"Unexpected error in start_command for chat_id {chat_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred. Please try again later.")
    finally:
        db.close()


async def show_phone_verification_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show phone number verification prompt."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Verify Phone Number", callback_data="verify_phone")],
        [InlineKeyboardButton("ℹ️ Why do I need to verify?", callback_data="why_verify")]
    ])
    
    message = (
        "🔔 **Live Lines Finder**\n\n"
        "To check your subscription status and enable notifications, "
        "we need to verify your phone number.\n\n"
        "This helps us link your Telegram account with your subscription."
    )
    
    await update.message.reply_text(
        message,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )


async def handle_verification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle phone verification callback buttons."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "verify_phone":
        # First, edit the message to remove the inline keyboard
        await query.edit_message_text(
            "Please share your contact information by clicking the button below.\n\n"
            "This will help us verify your subscription status."
        )
        
        # Then send a new message with the contact request keyboard
        contact_button = KeyboardButton(text="📱 Share Contact", request_contact=True)
        reply_markup = ReplyKeyboardMarkup([[contact_button]], one_time_keyboard=True, resize_keyboard=True)

        await query.message.reply_text(
            "👇 Click the button below to share your contact information:",
            reply_markup=reply_markup
        )
    
    elif query.data == "why_verify":
        message = (
            "**Why phone number verification?** 🤔\n\n"
            "• **Security**: Ensures only you can access your account\n"
            "• **Subscription Link**: Connects your Telegram to your paid subscription\n"
            "• **Notifications**: Enables us to send you line movement alerts\n\n"
            "Your phone number is only used for verification and notifications."
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Verify Now", callback_data="verify_phone")],
            [InlineKeyboardButton("🌐 Subscribe First", url="https://buy.stripe.com/3cs7tobZl17z0o05kk")]  # Replace with your website
        ])
        
        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='Markdown')


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles receiving contact information with Stripe verification."""
    chat_id = update.effective_chat.id
    contact = update.message.contact
    logger.info(f"Received contact information from chat_id: {chat_id}")

    if contact and contact.phone_number:
        # Standardize the phone number immediately when received
        raw_phone = contact.phone_number
        phone_number = standardize_phone_number(raw_phone)
        logger.info(f"Phone number received: {raw_phone} -> standardized: {phone_number} for chat_id: {chat_id}")

        # First, check if this phone number exists in Stripe
        customer_id, is_active, end_date = StripeService.find_customer_by_phone(phone_number)
        
        if not customer_id:
            # No Stripe customer found with this phone number
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Subscribe Now", url="https://buy.stripe.com/3cs7tobZl17z0o05kk")],  # Replace with your website
                [InlineKeyboardButton("❓ Need Help?", callback_data="need_help")]
            ])
            
            await update.message.reply_text(
                "❌ **No subscription found**\n\n"
                "We couldn't find an active subscription associated with this phone number.\n\n"
                "Please subscribe on our website first, then come back to verify your phone number.",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            return

        if not is_active:
            # Customer exists but subscription is not active
            await update.message.reply_text(
                "⚠️ **Subscription Inactive**\n\n"
                "We found your account, but your subscription appears to be inactive or expired.\n\n"
                "Please reactivate your subscription and try again.",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='Markdown'
            )
            return

        # Customer exists and has active subscription
        db_session_gen = get_db_session()
        db = next(db_session_gen)
        try:
            user = db.query(User).filter(User.chat_id == chat_id).first()
            if user:
                # Update existing user
                user.phone_number = phone_number
                user.stripe_customer_id = customer_id
                user.is_subscribed = True
                user.subscription_end_date = end_date
                db.commit()
                logger.info(f"Updated existing user {chat_id} with Stripe info.")
            else:
                # Create new user
                new_user = User(
                    chat_id=chat_id, 
                    phone_number=phone_number,
                    stripe_customer_id=customer_id,
                    is_subscribed=True,
                    subscription_end_date=end_date
                )
                db.add(new_user)
                db.commit()
                logger.info(f"Created new user {chat_id} with Stripe subscription.")

            # Link Telegram chat_id to Stripe customer
            StripeService.link_customer_to_telegram(customer_id, chat_id)
            
            # Format the success message based on whether we have an end date
            if end_date:
                end_date_str = end_date.strftime('%Y-%m-%d')
                welcome_message = (
                    f"✅ **Verification Successful!**\n\n"
                    f"Welcome! Your subscription is active until {end_date_str}.\n\n"
                    "🔔 You'll now receive live betting line notifications when significant changes occur.\n\n"
                    "Type /help to see available commands."
                )
            else:
                welcome_message = (
                    f"✅ **Verification Successful!**\n\n"
                    f"Welcome! Your subscription is active.\n\n"
                    "🔔 You'll now receive live betting line notifications when significant changes occur.\n\n"
                    "Type /help to see available commands."
                )
            
            await update.message.reply_text(
                welcome_message,
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='Markdown'
            )
            
        except SQLAlchemyError as e:
            logger.error(f"Database error in contact_handler for chat_id {chat_id}: {e}", exc_info=True)
            db.rollback()
            await update.message.reply_text(
                "A database error occurred while saving your information. Please try again.",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            logger.error(f"Unexpected error in contact_handler for chat_id {chat_id}: {e}", exc_info=True)
            db.rollback()
            await update.message.reply_text(
                "An unexpected error occurred while saving your information. Please try again.",
                reply_markup=ReplyKeyboardRemove()
            )
        finally:
            db.close()
    else:
        logger.warning(f"Could not read contact information for chat_id: {chat_id}. Contact object: {contact}")
        await update.message.reply_text(
            "Could not read your contact information properly. Please try sharing your contact again."
        )


def main() -> None:
    # Initialize the database
    try:
        init_db()
        logger.info("Database initialization complete.")
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}", exc_info=True)
        return  # Exit if DB init fails

    logger.info("Starting bot...")

    # Create the Application and pass it your bot's token.
    application = ApplicationBuilder().token(Config.TELEGRAM_BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(handle_verification_callback))
    application.add_handler(MessageHandler(filters.CONTACT, contact_handler))

    # Run the bot until the user presses Ctrl-C
    try:
        logger.info("Bot is starting to poll...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot polling was stopped by user (KeyboardInterrupt/SystemExit).")
    except Exception as e:
        logger.error(f"An unexpected error occurred during bot polling: {e}", exc_info=True)
    finally:
        logger.info("Bot application has finished.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Application failed to run: {e}", exc_info=True)
