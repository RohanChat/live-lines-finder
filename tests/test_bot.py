import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call # Added call for checking multiple calls

from sqlalchemy.orm import Session

from src.telegram_bot import start_command, contact_handler
from src.database import User

from telegram import Update, Chat, Message, User as TelegramUser, KeyboardButton, ReplyKeyboardMarkup, Contact
from telegram.ext import ContextTypes

@pytest.mark.asyncio
async def test_start_command_new_user(db_session: Session):
    """Test the start_command with a new user."""
    chat_id = 12345

    mock_update = MagicMock(spec=Update)
    mock_update.effective_chat = MagicMock(spec=Chat, id=chat_id)
    mock_update.message = MagicMock(spec=Message)
    mock_update.message.reply_text = AsyncMock() # start_command uses update.message.reply_text

    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE) # Not used by start_command for sending messages

    await start_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    args, kwargs = mock_update.message.reply_text.call_args

    assert "Welcome! To enable notifications" in args[0]
    assert isinstance(kwargs.get('reply_markup'), ReplyKeyboardMarkup)
    keyboard = kwargs.get('reply_markup').keyboard
    assert keyboard[0][0].text == "Share Contact"
    assert keyboard[0][0].request_contact is True

    user_in_db = db_session.query(User).filter(User.chat_id == chat_id).first()
    assert user_in_db is not None
    assert user_in_db.chat_id == chat_id
    assert user_in_db.phone_number is None

@pytest.mark.asyncio
async def test_start_command_existing_user_no_phone(db_session: Session):
    """Test the start_command with an existing user who has no phone number."""
    chat_id = 67890

    existing_user = User(chat_id=chat_id)
    db_session.add(existing_user)
    db_session.commit()

    mock_update = MagicMock(spec=Update)
    mock_update.effective_chat = MagicMock(spec=Chat, id=chat_id)
    mock_update.message = MagicMock(spec=Message)
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    await start_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    args, kwargs = mock_update.message.reply_text.call_args
    assert "Welcome! To enable notifications" in args[0]
    assert isinstance(kwargs.get('reply_markup'), ReplyKeyboardMarkup)

    user_count = db_session.query(User).filter(User.chat_id == chat_id).count()
    assert user_count == 1
    user_in_db = db_session.query(User).filter(User.chat_id == chat_id).first()
    assert user_in_db.phone_number is None

@pytest.mark.asyncio
async def test_start_command_existing_user_with_phone(db_session: Session):
    """Test the start_command with an existing user who already has a phone number."""
    chat_id = 13579
    phone_number = "+1234567890"

    existing_user = User(chat_id=chat_id, phone_number=phone_number)
    db_session.add(existing_user)
    db_session.commit()

    mock_update = MagicMock(spec=Update)
    mock_update.effective_chat = MagicMock(spec=Chat, id=chat_id)
    mock_update.message = MagicMock(spec=Message)
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    await start_command(mock_update, mock_context)

    assert mock_update.message.reply_text.call_count == 2

    # Check first call: "Welcome back..."
    call1_args, call1_kwargs = mock_update.message.reply_text.call_args_list[0]
    assert "Welcome back! Your phone number is already registered." in call1_args[0]
    assert 'reply_markup' not in call1_kwargs # First message has no special keyboard

    # Check second call: "Welcome! To enable notifications..." with button
    call2_args, call2_kwargs = mock_update.message.reply_text.call_args_list[1]
    assert "Welcome! To enable notifications" in call2_args[0]
    assert isinstance(call2_kwargs.get('reply_markup'), ReplyKeyboardMarkup)
    keyboard = call2_kwargs.get('reply_markup').keyboard
    assert keyboard[0][0].text == "Share Contact"
    assert keyboard[0][0].request_contact is True

    user_in_db = db_session.query(User).filter(User.chat_id == chat_id).first()
    assert user_in_db is not None
    assert user_in_db.phone_number == phone_number

@pytest.mark.asyncio
async def test_contact_handler_new_phone_for_existing_user(db_session: Session):
    """Test contact_handler saves a new phone number for an existing user."""
    chat_id = 24680
    new_phone_number = "0987654321"

    # Pre-populate user without a phone number
    existing_user = User(chat_id=chat_id)
    db_session.add(existing_user)
    db_session.commit()

    # Mock Update and Message objects
    mock_update = MagicMock(spec=Update)
    mock_update.effective_chat = MagicMock(spec=Chat, id=chat_id) # Not directly used by handler but good for completeness

    mock_message = MagicMock(spec=Message)
    mock_message.contact = MagicMock(spec=Contact)
    mock_message.contact.phone_number = new_phone_number
    mock_message.reply_text = AsyncMock() # contact_handler uses update.message.reply_text
    mock_update.message = mock_message

    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE) # Not used by contact_handler for sending

    await contact_handler(mock_update, mock_context)

    # Assertions
    # 1. Check if reply_text was called with confirmation
    mock_update.message.reply_text.assert_called_once()
    args, kwargs = mock_update.message.reply_text.call_args
    assert "Thank you! Your contact information has been saved successfully." in args[0]
    assert kwargs.get('reply_markup') is not None # Should be ReplyKeyboardRemove

    # 2. Verify phone number was updated in the database
    user_in_db = db_session.query(User).filter(User.chat_id == chat_id).first()
    assert user_in_db is not None
    assert user_in_db.phone_number == new_phone_number

# TODO:
# - Test contact_handler updating an existing phone number.
# - Test contact_handler when contact information is missing or invalid.
# - Test contact_handler for a user not found in DB (though start_command should prevent this).
# Ensure imports in test_bot.py are complete (e.g. Contact for mock_message.contact)
# Added `call` from unittest.mock.
# Corrected Chat mock: mock_update.effective_chat = MagicMock(spec=Chat, id=chat_id)
# Added Contact import.
# Added first test for contact_handler.
# Ensured reply_markup is checked for ReplyKeyboardRemove in contact_handler test (it's not None).
# ReplyKeyboardRemove is an object, so `isinstance` or checking its properties might be better.
# For now, `is not None` is a basic check. The actual bot code uses `ReplyKeyboardRemove()`.
from telegram import ReplyKeyboardRemove # Import for instanceof check

@pytest.mark.asyncio
async def test_contact_handler_saves_phone_and_removes_keyboard(db_session: Session): # Renamed for clarity
    chat_id = 24680
    new_phone_number = "0987654321"

    existing_user = User(chat_id=chat_id)
    db_session.add(existing_user)
    db_session.commit()

    mock_update = MagicMock(spec=Update)
    mock_update.effective_chat = MagicMock(spec=Chat, id=chat_id)

    mock_message = MagicMock(spec=Message)
    mock_message.contact = MagicMock(spec=Contact, phone_number=new_phone_number) # Simpler contact mock
    mock_message.reply_text = AsyncMock()
    mock_update.message = mock_message

    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    await contact_handler(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    args, kwargs = mock_update.message.reply_text.call_args
    assert "Thank you! Your contact information has been saved successfully." in args[0]
    assert isinstance(kwargs.get('reply_markup'), ReplyKeyboardRemove) # Specific check

    user_in_db = db_session.query(User).filter(User.chat_id == chat_id).first()
    assert user_in_db is not None
    assert user_in_db.phone_number == new_phone_number

# Removed the duplicated test code after renaming.
# The test `test_contact_handler_new_phone_for_existing_user` is now `test_contact_handler_saves_phone_and_removes_keyboard`
# and includes the `isinstance(..., ReplyKeyboardRemove)` check.
# This fulfills one test for contact_handler. More can be added later.
