from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from models import ListingStatus


# What the client sends when creating a listing
class FoodListingCreate(BaseModel):
    vendor_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    quantity: Optional[int] = Field(default=None, gt=0)
    weight_kg: Optional[float] = Field(default=None, gt=0)
    expiry: datetime
    image_url: Optional[str] = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def validate_required_pairs(self):
        if self.quantity is None and self.weight_kg is None:
            raise ValueError("Either quantity or weight_kg must be provided")
        return self

    @field_validator("expiry")
    @classmethod
    def expiry_must_be_future(cls, v: datetime) -> datetime:
        v_utc = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if v_utc <= datetime.now(tz=timezone.utc):
            raise ValueError("expiry must be in the future")
        return v


# What the client sends when updating a listing (all fields optional)
class FoodListingUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    quantity: Optional[int] = Field(None, gt=0)
    expiry: Optional[datetime] = None          # renamed from expiry_date to match model column
    status: Optional[ListingStatus] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)

    @field_validator("expiry")
    @classmethod
    def must_be_future(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return v
        v_utc = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if v_utc <= datetime.now(tz=timezone.utc):
            raise ValueError("expiry must be in the future")
        return v


# What the API returns
class FoodListingResponse(BaseModel):
    id: int
    vendor_id: str
    title: str
    description: Optional[str]
    quantity: Optional[int]
    weight_kg: Optional[float]
    expiry: datetime
    image_url: Optional[str]
    status: ListingStatus
    version: int
    latitude: Optional[float]
    longitude: Optional[float]
    geohash: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}

