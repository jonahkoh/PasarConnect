"""
Waitlist DB — the only persistent state owned by the Claim Service.

Table: waitlist_entries
  Tracks charities queued for a listing that is PENDING_COLLECTION.
  Position is FIFO — ordered by joined_at ascending.

Status lifecycle:
  WAITING   → charity is in queue, waiting for the active claimer to cancel
  PROMOTED  → charity was auto-assigned the item after cancellation
  CANCELLED → charity left the waitlist voluntarily (or was skipped at promotion)
"""
import os

from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

WAITLIST_DATABASE_URL = os.getenv(
    "WAITLIST_DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost/claim_db",
)

engine = create_async_engine(WAITLIST_DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id         = Column(Integer, primary_key=True)
    listing_id = Column(Integer, index=True, nullable=False)
    charity_id = Column(Integer, nullable=False)
    joined_at  = Column(DateTime, default=func.now())
    status     = Column(String(20), default="WAITING", nullable=False)

    __table_args__ = (
        # One charity can only appear once per listing on the waitlist
        UniqueConstraint("listing_id", "charity_id", name="uq_waitlist_listing_charity"),
    )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
