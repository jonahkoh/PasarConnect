import enum
from sqlalchemy import Column, DateTime, Enum, Integer, String, func, text
from database import Base


class ListingStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    PENDING = "PENDING"
    SOLD = "SOLD"


# Represents a row in the food_listings table
class FoodListing(Base):
    __tablename__ = "food_listings"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(String(1024), nullable=True)
    quantity = Column(Integer, nullable=False)
    expiry_date = Column(DateTime(timezone=True), nullable=False)

    status = Column(
        Enum(ListingStatus, name="listing_status_enum"),
        nullable=False,
        default=ListingStatus.AVAILABLE,
        server_default=text("'AVAILABLE'"),
    )

    # version is used for optimistic locking (Phase 1 · Step 2)
    version = Column(Integer, nullable=False, default=0, server_default=text("0"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
