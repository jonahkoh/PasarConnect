"""
Verification Service — database models and session factory.

Two tables track daily quotas used by the gRPC servicer:
  charity_claims        — one row per successful charity claim verification.
  public_user_purchases — one row per successful public-user purchase verification.

Both use the server clock (UTC) for created_at so that SELECT queries counting
today's events can compare against _today_start().
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost/verification_db",
)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


class CharityClaim(Base):
    """One row per successful VerifyCharity call — used for daily hoarding-quota checks."""

    __tablename__ = "charity_claims"

    id         = Column(Integer, primary_key=True)
    charity_id = Column(Integer, index=True, nullable=False)
    listing_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PublicUserPurchase(Base):
    """One row per successful VerifyPublicUser call — used for daily anti-scalping checks."""

    __tablename__ = "public_user_purchases"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, index=True, nullable=False)
    listing_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def today_start() -> datetime:
    """Midnight UTC — lower bound for today's quota count queries."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def init_db() -> None:
    """Create all tables if they don't already exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
