from __future__ import annotations
from contextlib import asynccontextmanager
import logging
import secrets
from fastapi import FastAPI, Depends, HTTPException, status, Security, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.config import Config
from src.chatbot.factory import create_chatbot
from src.database.models import User, UserSubscription
from src.database.session import get_db, get_db_session, init_db
from src.utils.utils import init_logging, standardize_phone_number, SubscriptionError

# --- 1. Initialization ---
# Initialize logging for the application.
init_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    Initializes all necessary resources like database and chatbot core.
    """
    logger.info("--- Application starting up ---")
    
    init_db(Config.DATABASE_URL)
    
    chatbot_core, _ = create_chatbot(platform_name="web", mode="prod")
    if not chatbot_core:
        raise RuntimeError("Fatal: Failed to create chatbot core.")
    app.state.chatbot_core = chatbot_core
    
    logger.info("--- Application startup complete. Ready to accept requests. ---")
    
    yield 
    
    logger.info("--- Application shutting down ---")

# # Use the factory to create a "headless" chatbot instance.
# # The factory handles loading config, feeds, etc.
# # We only need the core, not the messaging client (which is None for 'web').
# chatbot_core, _ = create_chatbot(platform_name="web", mode="prod")
# if not chatbot_core.redis:
#     raise RuntimeError("Redis client is not available. The web API requires Redis for session management.")


# --- 2. API Data Models ---
class PhoneLoginRequest(BaseModel):
    """Model for the initial phone number login."""
    phone_number: str = Field(..., example="+18576000135", description="The user's phone number in E.164 format.")

class LoginResponse(BaseModel):
    """Model for a successful login response, providing the session token."""
    session_id: str = Field(..., description="The temporary session token to use for all subsequent /chat requests.")

class ChatRequest(BaseModel):
    """Model for an incoming chat message, authenticated via session token."""
    session_id: str = Field(..., description="The session token obtained from a successful call to /auth/login.")
    user_input: str = Field(..., description="The text message from the user.")

class ChatResponse(BaseModel):
    """Model for the chatbot's reply."""
    reply: str = Field(..., description="The chatbot's text response.")


# --- 3. Authentication & Session Management ---
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)):
    """Dependency to validate the application's API key."""
    if not Config.WEB_APP_API_KEY:
        logger.critical("WEB_APP_API_KEY is not set in the environment!")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="API security is not configured.")
    
    if secrets.compare_digest(api_key, Config.WEB_APP_API_KEY):
        return api_key
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API Key.")

async def get_session_data(request: Request, session_id: str) -> dict:
    """
    Dependency to validate a session_id and retrieve user data from Redis.
    This acts as our user authentication for the /chat endpoint.
    """
    chatbot_core = request.app.state.chatbot_core
    session_key = f"web_session:{session_id}"
    user_data_raw = chatbot_core.redis.get(session_key)
    
    if not user_data_raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session token.")
    
    if isinstance(user_data_raw, bytes):
        line = user_data_raw.decode("utf-8", errors="replace")
    else:
        line = user_data_raw  # already a str

    try:
        user_id, phone_number = line.split("|", 1)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Corrupted session data.")
    
    return {"user_id": user_id, "phone_number": phone_number}


# --- 4. FastAPI Application ---
app = FastAPI(
    title="Betting Assistant API",
    description="A secure API to interact with the Betting Assistant chatbot.",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health", status_code=status.HTTP_200_OK, tags=["System"])
async def health_check():
    """A simple health check endpoint to confirm the API is running."""
    return {"status": "ok"}

@app.post("/auth/login", response_model=LoginResponse, dependencies=[Depends(get_api_key)], tags=["Authentication"])
async def login_with_phone(api_request: Request, request: PhoneLoginRequest, db: Session = Depends(get_db)):
    """
    Authenticates a user via their phone number.
    On success, it creates a session and returns a temporary session_id token.
    """
    chatbot_core = api_request.app.state.chatbot_core
    phone = standardize_phone_number(request.phone_number)
    user = db.query(User).filter(User.phone == phone).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User with this phone number not found.")

    active_subscription = db.query(UserSubscription).filter(UserSubscription.user_id == user.id, UserSubscription.active == True).first()
    if not active_subscription:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=f"No active subscription found for this user. Visit {chatbot_core.payment_url} to subscribe.")

    session_id = f"sess_{secrets.token_hex(24)}"
    session_key = f"web_session:{session_id}"
    session_value = f"{user.id}|{phone}" # Store both user_id and phone, separated by a pipe.

    # Store the session in Redis with a 24-hour expiry.
    chatbot_core.redis.set(session_key, session_value, ex=86400)
        
    return LoginResponse(session_id=session_id)

@app.post("/message", response_model=ChatResponse, dependencies=[Depends(get_api_key)], tags=["Chat"])
async def handle_chat(api_request: Request, request: ChatRequest, session: dict = Depends(get_session_data)):
    """
    Handles a user's message. Requires a valid session_id from /auth/login.
    """
    chatbot_core = api_request.app.state.chatbot_core
    user_id = session["user_id"]
    phone_number = session["phone_number"]

    try:
        logger.info(f"Processing chat for user_id: {user_id}")
        answer = chatbot_core.run_turn(
            user_input=request.user_input, 
            user_id=user_id, 
            chat_id=phone_number
        )
        return ChatResponse(reply=answer)

    except SubscriptionError as e:
        # This gracefully catches the specific error raised by the @require_subscription decorator.
        logger.info(f"Blocked API request for user {user_id} due to subscription error: {e}")
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="An active subscription is required. Please visit our website to subscribe."
        )
    except Exception as e:
        # This catches any other unexpected server errors during chatbot processing.
        logger.error(f"An unexpected error occurred for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing your request."
        )