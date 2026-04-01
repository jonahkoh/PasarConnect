import enum
import datetime
<<<<<<< copilot/create-test-cases-for-endpoints
from sqlalchemy import Enum as SAEnum, Float, Integer, String, DateTime, text, func
=======
from sqlalchemy import Enum as SAEnum, Integer, String, DateTime, Float, text, func
>>>>>>> main
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
    quantity    : Mapped[int | None]               = mapped_column(Integer, nullable=True)
    weight_kg   : Mapped[float | None]             = mapped_column(Float, nullable=True)
    image_url   : Mapped[str | None]               = mapped_column(String(1024), nullable=True)
    expiry      : Mapped[datetime.datetime]        = mapped_column(DateTime(timezone=True), nullable=False)
    status      : Mapped[ListingStatus]            = mapped_column(
        SAEnum(ListingStatus, name="listing_status_enum"),
        nullable=False,
        default=ListingStatus.AVAILABLE,
        server_default=text("'AVAILABLE'"),
    )
    version     : Mapped[int]                      = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    latitude    : Mapped[float | None]             = mapped_column(Float, nullable=True)
    longitude   : Mapped[float | None]             = mapped_column(Float, nullable=True)
    geohash     : Mapped[str | None]               = mapped_column(String(12), nullable=True, index=True)
    created_at  : Mapped[datetime.datetime]        = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at  : Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=func.now())

