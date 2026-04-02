"""
Verification Service — database models and session factory.

Three tables:
  charity_claims        — one row per successful VerifyCharity call (daily quota / anti-hoarding)
  public_user_purchases — one row per successful VerifyPublicUser call (daily purchase anti-scalping)
  charity_noshows       — one row per charity no-show, written via RecordNoShow RPC
                          (pattern-of-noshows check rejects charities before locking inventory)

OutSystems handles auth/JWT — this service only enforces business-rule limits.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

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
    """One row per approved VerifyCharity — counts toward the daily hoarding quota."""

    __tablename__ = "charity_claims"

    id         = Column(Integer, primary_key=True)
    charity_id = Column(Integer, index=True, nullable=False)
    listing_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PublicUserPurchase(Base):
    """One row per approved VerifyPublicUser — counts toward the daily anti-scalping quota."""

    __tablename__ = "public_user_purchases"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, index=True, nullable=False)
    listing_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CharityNoShow(Base):
    """One row per RecordNoShow call — charity failed to collect a claimed item.
    VerifyCharity counts recent no-shows and rejects if the pattern exceeds MAX_NOSHOWS."""

    __tablename__ = "charity_noshows"

    id         = Column(Integer, primary_key=True)
    charity_id = Column(Integer, index=True, nullable=False)
    claim_id   = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def today_start() -> datetime:
    """Midnight UTC — lower bound for today's quota count queries."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def noshows_window_start(days: int) -> datetime:
    """Start of the rolling no-show lookback window."""
    return datetime.now(timezone.utc) - timedelta(days=days)


async def init_db() -> None:
    """Create all tables if they don't already exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
