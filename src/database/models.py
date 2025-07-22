from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, Column, BigInteger, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

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

    sportsbook_preferences = relationship(
        "SportsbookPreference", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, chat_id={self.chat_id}, is_subscribed={self.is_subscribed})>"

class SportsbookPreference(Base):
    __tablename__ = "sportsbook_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    sportsbook_name = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="sportsbook_preferences")

    def __repr__(self) -> str:
        return (
            f"<SportsbookPreference(id={self.id}, user_id={self.user_id}, sportsbook_name={self.sportsbook_name})>"
        )
