"""
Pydantic schemas for Claim Log Service.
"""
import datetime

from pydantic import BaseModel, Field

from models import ClaimStatus


class LogCreate(BaseModel):
    listing_id: int = Field(..., gt=0)
    charity_id: int = Field(..., gt=0)
    listing_version: int = Field(..., ge=0)
    status: ClaimStatus = ClaimStatus.PENDING_COLLECTION


class LogUpdate(BaseModel):
    status: ClaimStatus


class LogResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    listing_id: int
    charity_id: int
    listing_version: int
    status: ClaimStatus
    created_at: datetime.datetime
    updated_at: datetime.datetime | None
