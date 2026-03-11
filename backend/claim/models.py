import enum
import datetime
from sqlalchemy import Integer, Enum, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class ClaimStatus(str, enum.Enum):
    PENDING   = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Claim(Base):
    __tablename__ = "claims"

    id              : Mapped[int]         = mapped_column(Integer,     primary_key=True, index=True)
    listing_id      : Mapped[int]         = mapped_column(Integer,     nullable=False, index=True)
    charity_id      : Mapped[int]         = mapped_column(Integer,     nullable=False)
    status          : Mapped[ClaimStatus] = mapped_column(Enum(ClaimStatus), default=ClaimStatus.PENDING)
    listing_version : Mapped[int]         = mapped_column(Integer,     nullable=False)
    created_at      : Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
