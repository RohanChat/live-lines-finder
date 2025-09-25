from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.database import User
from .models import Base
from supabase import create_client



engine = None
SessionLocal = None

def init_db(database_url: str):
    """
    Initializes the database engine and session factory.
    This should be called once when the application starts.
    """
    global engine, SessionLocal
    if engine:
        return

    print(f"Attempting to connect to database at: {database_url}")
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager to get a database session."""
    if not SessionLocal:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency to get a database session."""
    if not SessionLocal:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_by_phone(db, phone_number: str):
    """
    Retrieve a user by their phone value in the user table.
    Then return the user object.
    """
    print(f"Attempting to connect to database at: {Config.DATABASE_URL}")
    if not db:
        raise ValueError("Database session is not initialized.")
    return db.query(User).filter(User.phone == phone_number).first()
