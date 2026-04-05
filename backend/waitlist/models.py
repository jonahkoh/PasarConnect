import enum

from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from sqlalchemy.sql import func

from database import Base


class WaitlistEntryStatus(str, enum.Enum):
    """All valid status values for a WaitlistEntry row."""
    QUEUING   = "QUEUING"    # registered during the 2-min queue window (pre-ranking)
    WAITING   = "WAITING"    # in queue after the window closed; awaiting their turn
    OFFERED   = "OFFERED"    # rank-1 charity notified; awaiting their accept/decline
    CANCELLED = "CANCELLED"  # voluntarily left, declined the offer, no-show, or listing sold
    COLLECTED = "COLLECTED"  # charity accepted the offer and successfully collected the item


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id          = Column(Integer, primary_key=True, index=True)
    listing_id  = Column(Integer, index=True, nullable=False)
    charity_id  = Column(Integer, nullable=False)
    joined_at   = Column(DateTime, server_default=func.now(), nullable=False)
    status      = Column(String(20), default="WAITING", nullable=False)
    # Queue-window ranking fields (NULL for entries that joined after the window closed)
    rank        = Column(Integer, nullable=True)   # 1 = highest priority
    score       = Column(Integer, nullable=True)   # completed_claims - (noshow_count * 2)
    resolved_at = Column(DateTime, nullable=True)  # timestamp when window resolution ran

    __table_args__ = (
        # One charity can only appear once per listing on the waitlist
        UniqueConstraint("listing_id", "charity_id", name="uq_waitlist_listing_charity"),
    )
