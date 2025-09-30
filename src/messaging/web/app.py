from __future__ import annotations
from contextlib import asynccontextmanager
import logging
import secrets
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Security, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.config import Config
from src.chatbot.factory import create_chatbot
from src.database.models import User, UserSubscription
from src.database.session import get_db, init_db
from src.utils.utils import init_logging, standardize_phone_number, SubscriptionError

# --- 1) Initialization ---
init_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("--- Application starting up ---")
    init_db(Config.DATABASE_URL)

    chatbot_core, _ = create_chatbot(platform_name="web", mode="prod")
    if not chatbot_core:
        raise RuntimeError("Fatal: Failed to create chatbot core.")
    app.state.chatbot_core = chatbot_core

    logger.info("--- Application startup complete. Ready to accept requests. ---")
    logger.info(f"TOA_MAPPING keys: {list((Config.TOA_MAPPING or {}).keys())}")
    yield
    logger.info("--- Application shutting down ---")

# --- 2) API Models ---
class PhoneLoginRequest(BaseModel):
    phone_number: str = Field(..., example="+18576000135", description="User phone in E.164 format.")

class LoginResponse(BaseModel):
    session_id: str = Field(..., description="Use this in /message requests.")

class ChatRequest(BaseModel):
    # Browser (session) flow:
    session_id: Optional[str] = Field(None, description="From /auth/login (browser flow).")
    # Server-to-server (partners) flow (with X-API-Key):
    user_id: Optional[str] = Field(None, description="Partner end-user ID (required with X-API-Key).")
    chat_id: Optional[str] = Field(None, description="Conversation/chat ID (required with X-API-Key).")
    # Common:
    user_input: str = Field(..., description="User message text.")

class ChatResponse(BaseModel):
    reply: str = Field(..., description="Chatbot response text.")

# --- 3) Auth helpers (API key OR session) ---
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
session_header = APIKeyHeader(name="X-Session-Id", auto_error=False)

def is_valid_api_key(candidate: Optional[str]) -> bool:
    """Accept one or multiple comma-separated keys in WEB_APP_API_KEY."""
    if not candidate:
        return False
    raw = (Config.WEB_APP_API_KEY or "").strip()
    allowed = [k.strip() for k in raw.split(",") if k.strip()]
    return any(secrets.compare_digest(candidate, k) for k in allowed)

async def allow_api_key_or_session(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
    session_id_hdr: Optional[str] = Security(session_header),
):
    """
    Accept either:
      - X-API-Key (server-to-server), OR
      - session_id (browser) via X-Session-Id header or JSON body.
    """
    # 1) API key mode (partners / server-to-server)
    if api_key and is_valid_api_key(api_key):
        return {"mode": "apikey"}

    # 2) Session mode (browser)
    session_id = session_id_hdr
    if not session_id:
        try:
            body = await request.json()
            session_id = body.get("session_id")
        except Exception:
            session_id = None

    if session_id:
        session = await get_session_data(request, session_id)
        request.state.session = session
        return {"mode": "session", "session": session}

    # 3) Neither provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Provide X-API-Key (server) or session_id / X-Session-Id (browser).",
    )

async def get_session_data(request: Request, session_id: str) -> dict:
    """Validate session_id in Redis and return user data."""
    chatbot_core = request.app.state.chatbot_core
    session_key = f"web_session:{session_id}"
    user_data_raw = chatbot_core.redis.get(session_key)

    if not user_data_raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session token.")

    line = user_data_raw.decode("utf-8", errors="replace") if isinstance(user_data_raw, bytes) else user_data_raw
    try:
        user_id, phone_number = line.split("|", 1)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Corrupted session data.")

    return {"user_id": user_id, "phone_number": phone_number}

# --- 4) FastAPI app & routes ---
app = FastAPI(
    title="Betting Assistant API",
    description="API to interact with the Betting Assistant chatbot.",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://oddsmate.vercel.app", "https://oddsmate.ai", "https://www.oddsmate.ai"],  # The origin of your frontend app
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.get("/health", status_code=status.HTTP_200_OK, tags=["System"])
async def health_check():
    return {"status": "ok"}

# Browser testers enter the one known phone; no API key; no OTP.
@app.post("/auth/login", response_model=LoginResponse, tags=["Authentication"])
async def login_with_phone(api_request: Request, request: PhoneLoginRequest, db: Session = Depends(get_db)):
    chatbot_core = api_request.app.state.chatbot_core
    phone = standardize_phone_number(request.phone_number)

    # Must match a real user row
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User with this phone number not found.")

    # Active subscription required (no 'self.product_id' here)
    active_subscription = db.query(UserSubscription).filter(
        UserSubscription.user_id == user.id,
        UserSubscription.active == True
    ).first()
    if not active_subscription:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"No active subscription found for this user. Visit {chatbot_core.payment_url} to subscribe."
        )

    session_id = f"sess_{secrets.token_hex(24)}"
    session_key = f"web_session:{session_id}"
    session_value = f"{user.id}|{phone}"
    chatbot_core.redis.set(session_key, session_value, ex=86400)  # 24h

    return LoginResponse(session_id=session_id)

# Unified /message: session (browser) OR X-API-Key (partners)
@app.post("/message", response_model=ChatResponse, tags=["Chat"])
async def handle_chat(
    api_request: Request,
    request: ChatRequest,
    auth = Depends(allow_api_key_or_session)
):
    chatbot_core = api_request.app.state.chatbot_core

    if auth["mode"] == "session":
        sess = api_request.state.session
        user_id = sess["user_id"]
        chat_id = sess["phone_number"]
    else:
        # API key flow: require user_id and chat_id in body
        if not request.user_id or not request.chat_id:
            raise HTTPException(status_code=400, detail="user_id and chat_id are required when using X-API-Key.")
        user_id = request.user_id
        chat_id = request.chat_id

    try:
        logger.info(f"Processing chat for user_id={user_id}")
        answer = chatbot_core.run_turn(
            user_input=request.user_input,
            user_id=user_id,
            chat_id=chat_id
        )
        return ChatResponse(reply=answer)
    except SubscriptionError as e:
        logger.info(f"Blocked API request for user {user_id} due to subscription error: {e}")
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="An active subscription is required."
        )
    except Exception as e:
        logger.error(f"Unexpected error for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error."
        )
