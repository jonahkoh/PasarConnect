import datetime
import enum

from pydantic import BaseModel, Field


class ClaimStatus(str, enum.Enum):
    """Public status values returned by the Claim Orchestrator."""

    PENDING_COLLECTION = "PENDING_COLLECTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimCreate(BaseModel):
    """What the client sends when creating a claim."""

    listing_id: int = Field(..., gt=0)
    charity_id: int = Field(..., gt=0)
    listing_version: int = Field(..., ge=0)  # optimistic-lock version seen by the client


class ClaimResponse(BaseModel):
    """What the orchestrator returns after a successful workflow."""

    id: int
    listing_id: int
    charity_id: int
    status: ClaimStatus
    listing_version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime | None
