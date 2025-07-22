from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import Config
from .models import Base

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
