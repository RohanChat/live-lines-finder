from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, create_engine, Column, BigInteger, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config import Config

# Define a base class for declarative models
Base = declarative_base()

# Define the User model
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(Text, nullable=True)
    phone_number = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    chat_id = Column(BigInteger, unique=True, nullable=False, index=True)
    
    # Subscription fields
    is_subscribed = Column(Boolean, default=False, nullable=False)
    stripe_customer_id = Column(Text, nullable=True)
    subscription_end_date = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<User(id={self.id}, chat_id={self.chat_id}, is_subscribed={self.is_subscribed})>"

# Create a database engine using the URL from Config
engine = create_engine(Config.DATABASE_URL)

# Create a SessionLocal class to generate database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Function to create database tables
def init_db():
    """
    Initializes the database by creating all tables defined in the Base metadata.
    """
    Base.metadata.create_all(bind=engine)
    print("Database initialized and tables created (if they didn't exist).")

# Function to get a database session
def get_db_session():
    """
    Provides a database session.
    The caller is responsible for closing the session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# This is primarily for initial setup.
# In a full application, this would be handled by a startup script or managed differently.
if __name__ == "__main__":
    init_db()
