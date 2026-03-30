from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from models import ListingStatus


# What the client sends when creating a listing
class FoodListingCreate(BaseModel):
    vendor_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
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
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}
