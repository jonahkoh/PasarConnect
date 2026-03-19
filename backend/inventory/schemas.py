from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from models import ListingStatus


# What the client sends when creating a listing
class FoodListingCreate(BaseModel):
    vendor_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    quantity: int = Field(..., gt=0)
    expiry_date: datetime
    address: Optional[str] = Field(None, max_length=512)

    @field_validator("expiry_date")
    @classmethod
    def must_be_future(cls, v: datetime) -> datetime:
        v_utc = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if v_utc <= datetime.now(tz=timezone.utc):
            raise ValueError("expiry_date must be in the future")
        return v


# What the client sends when updating a listing
class FoodListingUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    quantity: Optional[int] = Field(None, gt=0)
    expiry_date: Optional[datetime] = None
    status: Optional[ListingStatus] = None
    address: Optional[str] = Field(None, max_length=512)

    @field_validator("expiry_date")
    @classmethod
    def validate_expiry_date(cls, v: datetime) -> datetime:
        if v is None:
            return v
        v_utc = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if v_utc <= datetime.now(tz=timezone.utc):
            raise ValueError("expiry_date must be in the future")
        return v


# What the API returns
class FoodListingResponse(BaseModel):
    id: int
    vendor_id: str
    title: str
    description: Optional[str]
    quantity: int
    expiry_date: datetime
    address: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    geohash: Optional[str]
    status: ListingStatus
    version: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}
