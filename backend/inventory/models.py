import enum
import datetime
from sqlalchemy import Enum as SAEnum, Integer, String, DateTime, text, func, Float
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class ListingStatus(str, enum.Enum):
    AVAILABLE          = "AVAILABLE"
    PENDING_PAYMENT    = "PENDING_PAYMENT"
    PENDING_COLLECTION = "PENDING_COLLECTION"
    SOLD_PENDING_COLLECTION = "SOLD_PENDING_COLLECTION"
    SOLD               = "SOLD"


# Represents a row in the food_listings table.
class FoodListing(Base):
    __tablename__ = "food_listings"

    id          : Mapped[int]                      = mapped_column(Integer, primary_key=True, index=True)
    vendor_id   : Mapped[str]                      = mapped_column(String(64), nullable=False, index=True)
    title       : Mapped[str]                      = mapped_column(String(255), nullable=False)
    description : Mapped[str | None]               = mapped_column(String(1024), nullable=True)
    quantity    : Mapped[int]                      = mapped_column(Integer, nullable=False)
    expiry_date : Mapped[datetime.datetime]        = mapped_column(DateTime(timezone=True), nullable=False)
    latitude    : Mapped[float | None]             = mapped_column(Float, nullable=True, index=True)
    longitude   : Mapped[float | None]             = mapped_column(Float, nullable=True, index=True)
    geohash     : Mapped[str | None]               = mapped_column(String(12), nullable=True, index=True)
    status      : Mapped[ListingStatus]            = mapped_column(
        SAEnum(ListingStatus, name="listing_status_enum"),
        nullable=False,
        default=ListingStatus.AVAILABLE,
        server_default=text("'AVAILABLE'"),
    )
    version     : Mapped[int]                      = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at  : Mapped[datetime.datetime]        = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at  : Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=func.now())
