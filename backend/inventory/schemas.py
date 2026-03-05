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

    @field_validator("expiry_date")     # need to change it to automatically validate that the expiry_date is in the future
    @classmethod
    def must_be_future(cls, v: datetime) -> datetime:
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
    status: ListingStatus
    version: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}
