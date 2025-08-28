from datetime import datetime, UTC
from enum import Enum
import uuid
from sqlalchemy import Boolean, DateTime, Column, BigInteger, Text, ForeignKey, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(Text, nullable=True)
    phone = Column(Text, unique=True, nullable=True)
    telegram_chat_id = Column(BigInteger, unique=True, nullable=True, index=True)
    imessage_chat_id = Column(BigInteger, nullable=True)
    stripe_customer_id = Column(Text, unique=True, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=func.now())

    user_subscriptions = relationship(
        "UserSubscription", back_populates="user", cascade="all, delete-orphan"
    )
    sportsbook_preferences = relationship(
        "SportsbookPreference", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_chat_id={self.telegram_chat_id})>"

class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    id = Column(Text, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    stripe_subscription_id = Column(Text, nullable=True)
    price_id = Column(Text, nullable=True)
    quantity = Column(BigInteger, default=1)
    current_period_end = Column(DateTime, nullable=True)
    status = Column(Text, nullable=True)
    trial_end = Column(DateTime, nullable=True)
    active = Column(Boolean, nullable=True)
    product_id = Column(Text, ForeignKey("products.id", onupdate="CASCADE", ondelete="SET DEFAULT"), nullable=True)

    user = relationship("User", back_populates="user_subscriptions")
    product = relationship("Product", back_populates="user_subscriptions")

class Product(Base):
    __tablename__ = "products"

    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    active = Column(Boolean, nullable=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    user_subscriptions = relationship("UserSubscription", back_populates="product")

class Sportsbook(Base):
    __tablename__ = "sportsbooks"

    id = Column(BigInteger, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    identifier = Column(Text, nullable=False, unique=True)
    region = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    sportsbook_preferences = relationship(
        "SportsbookPreference", back_populates="sportsbook"
    )

class SportsbookPreference(Base):
    __tablename__ = "sportsbook_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    sportsbook_id = Column(BigInteger, ForeignKey("sportsbooks.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "sportsbook_id", name="uq_user_sportsbook"),
    )

    user = relationship("User", back_populates="sportsbook_preferences")
    sportsbook = relationship("Sportsbook", back_populates="sportsbook_preferences")
