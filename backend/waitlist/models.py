from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from sqlalchemy.sql import func

from database import Base


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id         = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, index=True, nullable=False)
    charity_id = Column(Integer, nullable=False)
    joined_at  = Column(DateTime, server_default=func.now(), nullable=False)
    status     = Column(String(20), default="WAITING", nullable=False)

    __table_args__ = (
        # One charity can only appear once per listing on the waitlist
        UniqueConstraint("listing_id", "charity_id", name="uq_waitlist_listing_charity"),
    )
