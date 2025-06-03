import logging
import asyncio # Added for asyncio.run(main())

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from sqlalchemy.exc import SQLAlchemyError # Added for specific DB error handling

from src.config import Config
from src.database import get_db_session, User, init_db

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command."""
    chat_id = update.effective_chat.id
    logger.info(f"Received /start command from chat_id: {chat_id}")

    db_session_gen = get_db_session()
    db = next(db_session_gen)
    try:
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if not user:
            logger.info(f"New user detected. Creating user entry for chat_id: {chat_id}")
            new_user = User(chat_id=chat_id)
            db.add(new_user)
            db.commit()
            logger.info(f"User entry created for chat_id: {chat_id}")
        else:
            logger.info(f"Existing user {chat_id} initiated /start.")
            # Optionally, update user details or log restart
            if user.phone_number:
                await update.message.reply_text(
                    "Welcome back! Your phone number is already registered. "
                    "If you wish to update it, please share your contact again."
                )
            else: # User exists but phone number was not previously provided
                 logger.info(f"Existing user {chat_id} does not have a phone number. Requesting contact.")


        # Request contact information
        contact_button = KeyboardButton(text="Share Contact", request_contact=True)
        reply_markup = ReplyKeyboardMarkup([[contact_button]], one_time_keyboard=True, resize_keyboard=True)

        await update.message.reply_text(
            "Welcome! To enable notifications, please share your contact information by clicking the button below.",
            reply_markup=reply_markup
        )
    except SQLAlchemyError as e:
        logger.error(f"Database error in start_command for chat_id {chat_id}: {e}", exc_info=True)
        db.rollback()
        await update.message.reply_text("A database error occurred. Please try again later.")
    except Exception as e:
        logger.error(f"Unexpected error in start_command for chat_id {chat_id}: {e}", exc_info=True)
        db.rollback() # Rollback in case it's a DB error not caught by SQLAlchemyError
        await update.message.reply_text("An unexpected error occurred. Please try again later.")
    finally:
        db.close()


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles receiving contact information."""
    chat_id = update.effective_chat.id
    contact = update.message.contact
    logger.info(f"Received contact information from chat_id: {chat_id}")

    if contact and contact.phone_number:
        phone_number = contact.phone_number
        logger.info(f"Phone number received: {phone_number} for chat_id: {chat_id}")

        db_session_gen = get_db_session()
        db = next(db_session_gen)
        try:
            user = db.query(User).filter(User.chat_id == chat_id).first()
            if user:
                user.phone_number = phone_number
                db.commit()
                logger.info(f"Phone number {phone_number} saved for user {chat_id}.")
                await update.message.reply_text(
                    "Thank you! Your contact information has been saved successfully.",
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                # This case should ideally not happen if /start is always called first
                # and creates a user entry. But as a fallback:
                logger.warning(f"User with chat_id {chat_id} not found. Creating new user with phone number.")
                new_user = User(chat_id=chat_id, phone_number=phone_number)
                db.add(new_user)
                db.commit()
                await update.message.reply_text(
                    "Thank you! Your contact information has been saved.",
                    reply_markup=ReplyKeyboardRemove()
                )
        except SQLAlchemyError as e:
            logger.error(f"Database error in contact_handler for chat_id {chat_id}: {e}", exc_info=True)
            db.rollback()
            await update.message.reply_text(
                "A database error occurred while saving your contact. Please try again.",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            logger.error(f"Unexpected error in contact_handler for chat_id {chat_id}: {e}", exc_info=True)
            db.rollback() # Rollback in case it's a DB error not caught by SQLAlchemyError
            await update.message.reply_text(
                "An unexpected error occurred while saving your contact. Please try again.",
                reply_markup=ReplyKeyboardRemove()
            )
        finally:
            db.close()
    else:
        logger.warning(f"Could not read contact information for chat_id: {chat_id}. Contact object: {contact}")
        await update.message.reply_text(
            "Could not read your contact information properly. Please try sharing your contact again."
        )


async def main() -> None:
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
    application.add_handler(MessageHandler(filters.CONTACT, contact_handler))

    # Run the bot until the user presses Ctrl-C
    try:
        logger.info("Bot is starting to poll...")
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot polling was stopped by user (KeyboardInterrupt/SystemExit).")
    except Exception as e:
        logger.error(f"An unexpected error occurred during bot polling: {e}", exc_info=True)
    finally:
        logger.info("Bot application has finished.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Application failed to run: {e}", exc_info=True)
