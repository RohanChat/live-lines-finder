from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import Config
from database import User
from .models import Base
from supabase import create_client
print(f"Attempting to connect to database at: {Config.DATABASE_URL}")
engine = create_engine(Config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)



def init_db():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
    print("Database initialized and tables created (if they didn't exist).")


def get_db_session():
    """Yield a database session."""
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
