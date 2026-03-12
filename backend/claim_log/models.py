"""
SQLAlchemy 2.0 model for claim state records.
"""
import datetime
import enum

from sqlalchemy import DateTime, Enum as SAEnum, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class ClaimStatus(str, enum.Enum):
    PENDING_COLLECTION = "PENDING_COLLECTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimRecord(Base):
    __tablename__ = "claim_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    listing_id: Mapped[int] = mapped_column(Integer, index=True)
    charity_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[ClaimStatus] = mapped_column(
        SAEnum(ClaimStatus), default=ClaimStatus.PENDING_COLLECTION
    )
    listing_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
