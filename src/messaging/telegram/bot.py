import logging
from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
from sqlalchemy.exc import SQLAlchemyError

from ...config import Config
from ...database import get_db_session, User, init_db
from ...stripe_service import StripeService
from ...utils.phone_utils import standardize_phone_number
from ..base import BaseMessagingClient


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class TelegramBot(BaseMessagingClient):
    def __init__(self, token: str):
        self.application = ApplicationBuilder().token(token).build()

    async def send_message(self, chat_id, text: str, **kwargs):
        await self.application.bot.send_message(chat_id=chat_id, text=text, **kwargs)

    def register_command_handler(self, command: str, handler):
        self.application.add_handler(CommandHandler(command, handler))

    def register_message_handler(self, filter_obj, handler):
        self.application.add_handler(MessageHandler(filter_obj, handler))

    def register_callback_query_handler(self, handler):
        self.application.add_handler(CallbackQueryHandler(handler))

    def start(self):
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command with phone number verification."""
    chat_id = update.effective_chat.id
    logger.info(f"Received /start command from chat_id: {chat_id}")

    db_session_gen = get_db_session()
    db = next(db_session_gen)
    try:
        user = db.query(User).filter(User.chat_id == chat_id).first()

        if user and user.phone_number:
            customer_id, is_active, end_date = StripeService.find_customer_by_phone(user.phone_number)

            if customer_id and is_active:
                if not user.stripe_customer_id:
                    user.stripe_customer_id = customer_id
                    user.is_subscribed = True
                    user.subscription_end_date = end_date
                    db.commit()

                await update.message.reply_text(
                    "Welcome back! ✅ Your subscription is active.\n\n"
                    "You'll receive live betting line notifications when significant changes occur."
                )
                return
            elif customer_id and not is_active:
                await update.message.reply_text(
                    "Your subscription appears to be inactive or expired. 😞\n\n"
                    "Please visit our website to reactivate your subscription or contact support."
                )
                return

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
    query = update.callback_query
    await query.answer()

    if query.data == "verify_phone":
        await query.edit_message_text(
            "Please share your contact information by clicking the button below.\n\n"
            "This will help us verify your subscription status."
        )

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
            [InlineKeyboardButton("🌐 Subscribe First", url="https://buy.stripe.com/3cs7tobZl17z0o05kk")]
        ])

        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='Markdown')

    elif query.data == "retry_verification":
        await query.edit_message_text(
            "Let's try the verification again. Please share your contact information by clicking the button below.\n\n"
            "Make sure you're using the same phone number associated with your subscription."
        )

        contact_button = KeyboardButton(text="📱 Share Contact", request_contact=True)
        reply_markup = ReplyKeyboardMarkup([[contact_button]], one_time_keyboard=True, resize_keyboard=True)

        await query.message.reply_text(
            "👇 Click the button below to share your contact information:",
            reply_markup=reply_markup
        )


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    contact = update.message.contact
    logger.info(f"Received contact information from chat_id: {chat_id}")

    if contact and contact.phone_number:
        raw_phone = contact.phone_number
        phone_number = standardize_phone_number(raw_phone)
        logger.info(f"Phone number received: {raw_phone} -> standardized: {phone_number} for chat_id: {chat_id}")

        customer_id, is_active, end_date = StripeService.find_customer_by_phone(phone_number)

        if not customer_id:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Subscribe Now\n(USE SAME PHONE NUMBER)", url="https://buy.stripe.com/3cs7tobZl17z0o05kk")],
                [InlineKeyboardButton("🔄 Re-try Verification", callback_data="retry_verification")],
            ])

            await update.message.reply_text(
                "❌ **No subscription found**\n\n"
                "We couldn't find an active subscription associated with this phone number.\n\n"
                "Please subscribe on our website first, then come back to verify your phone number.",
                reply_markup=keyboard,
                parse_mode='Markdown',
            )
            return

        if not is_active:
            await update.message.reply_text(
                "⚠️ **Subscription Inactive**\n\n"
                "We found your account, but your subscription appears to be inactive or expired.\n\n"
                "Please reactivate your subscription and try again.",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='Markdown',
            )
            return

        db_session_gen = get_db_session()
        db = next(db_session_gen)
        try:
            user = db.query(User).filter(User.chat_id == chat_id).first()
            if user:
                user.phone_number = phone_number
                user.stripe_customer_id = customer_id
                user.is_subscribed = True
                user.subscription_end_date = end_date
                db.commit()
                logger.info(f"Updated existing user {chat_id} with Stripe info.")
            else:
                new_user = User(
                    chat_id=chat_id,
                    phone_number=phone_number,
                    stripe_customer_id=customer_id,
                    is_subscribed=True,
                    subscription_end_date=end_date,
                )
                db.add(new_user)
                db.commit()
                logger.info(f"Created new user {chat_id} with Stripe subscription.")

            StripeService.link_customer_to_telegram(customer_id, chat_id)

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
                parse_mode='Markdown',
            )

        except SQLAlchemyError as e:
            logger.error(f"Database error in contact_handler for chat_id {chat_id}: {e}", exc_info=True)
            db.rollback()
            await update.message.reply_text(
                "A database error occurred while saving your information. Please try again.",
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception as e:
            logger.error(f"Unexpected error in contact_handler for chat_id {chat_id}: {e}", exc_info=True)
            db.rollback()
            await update.message.reply_text(
                "An unexpected error occurred while saving your information. Please try again.",
                reply_markup=ReplyKeyboardRemove(),
            )
        finally:
            db.close()
    else:
        logger.warning(f"Could not read contact information for chat_id: {chat_id}. Contact object: {contact}")
        await update.message.reply_text(
            "Could not read your contact information properly. Please try sharing your contact again."
        )


def main() -> None:
    try:
        init_db()
        logger.info("Database initialization complete.")
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}", exc_info=True)
        return

    logger.info("Starting Telegram bot...")

    bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN)
    bot.register_command_handler("start", start_command)
    bot.register_callback_query_handler(handle_verification_callback)
    bot.register_message_handler(filters.CONTACT, contact_handler)
    bot.start()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Application failed to run: {e}", exc_info=True)

