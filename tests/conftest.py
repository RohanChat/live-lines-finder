import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from database import Base, init_db as actual_init_db, get_db_session as actual_get_db_session, engine as actual_engine

# Store the original engine and SessionLocal
OriginalEngine = actual_engine
OriginalSessionLocal = None # Will be dynamically captured if needed, or we just replace engine

@pytest.fixture(scope="function") # Use "function" scope for isolation between tests
def db_session():
    """
    Pytest fixture to provide a database session with an in-memory SQLite DB.
    Patches Config.DATABASE_URL for the duration of the test.
    Initializes the DB schema and cleans up after the test.
    """
    # Setup: In-memory SQLite database
    # Patch the engine used by src.database.init_db and src.database.get_db_session
    # This is more direct than patching Config.DATABASE_URL if src.database directly uses an engine instance.

    # Create a new engine for the in-memory SQLite database
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Create a new SessionLocal for this engine
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    # Patch the engine and SessionLocal in src.database
    # We need to patch where these are LOOKED UP, not just where they are defined.
    # init_db uses `engine` from its own module.
    # get_db_session uses `SessionLocal` from its own module.

    with patch('database.engine', test_engine), \
         patch('database.SessionLocal', TestSessionLocal), \
         patch('database.session.engine', test_engine), \
         patch('database.session.SessionLocal', TestSessionLocal), \
         patch('src.database.engine', test_engine), \
         patch('src.database.SessionLocal', TestSessionLocal), \
         patch('src.database.session.engine', test_engine), \
         patch('src.database.session.SessionLocal', TestSessionLocal):

        # Initialize the database schema
        # init_db() in src.database uses Base.metadata.create_all(bind=engine)
        # So, if we've patched src.database.engine, it should use the test_engine
        actual_init_db() # This will now use the patched test_engine

        # Create a session
        db = TestSessionLocal()

        try:
            yield db  # Provide the session to the test
        finally:
            db.close()
            # Drop all tables to clean up
            # Base.metadata.drop_all(bind=test_engine) # Ensure this uses the test_engine
            # For function scope, a new in-memory DB is created each time, so drop_all might be redundant
            # but good for explicit cleanup if scope were larger or DB persisted.
            # For :memory:, the DB is discarded when the connection is closed.
            # However, if Base is shared, drop_all ensures a clean slate for metadata if needed.
            Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def mock_bot_app_components(db_session):
    """
    Provides a mock Telegram Application, Bot, and a test db_session.
    The db_session from the db_session fixture is used.
    """
    # Mock Bot
    mock_bot = MagicMock(spec=Bot)
    mock_bot.send_message = AsyncMock()
    mock_bot.edit_message_text = AsyncMock()
    mock_bot.answer_callback_query = AsyncMock()

    # Mock Application (or ApplicationBuilder, depending on what's used)
    # If ApplicationBuilder is used and then .build() is called,
    # you might need to patch ApplicationBuilder().token().build() to return a mock application
    # that then has this mock_bot.
    # For simplicity, if the handlers directly use context.bot, providing a mock bot in context is key.

    # The db_session is already handled by the db_session fixture and will be injected
    # into tests that request mock_bot_app_components AND db_session.
    # Or, just inject db_session separately. This fixture focuses on bot mocks.

    return {
        "bot": mock_bot,
        # application mock can be added if needed for testing application setup
    }

# Note: The above mock_bot_app_components is a starting point.
# For actual tests in test_bot.py, we will likely create more specific mocks
# for Update, ContextTypes, etc., directly within the test functions or as smaller fixtures.
# The db_session fixture is the most critical part from this step.
# We also need to import Bot, AsyncMock, MagicMock from unittest.mock for this conftest.py to be self-contained for these mocks.
# Let's add those imports.
from telegram import Bot # Already there for spec
from unittest.mock import AsyncMock, MagicMock # Add these
