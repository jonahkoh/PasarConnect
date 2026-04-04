import datetime

from pydantic import BaseModel, ConfigDict, Field


class WaitlistJoin(BaseModel):
    """Body sent when a charity wants to join the waitlist."""
    charity_id: int = Field(..., gt=0)


class WaitlistEntryOut(BaseModel):
    """One entry returned by GET /waitlist/{listing_id}/entries."""
    id: int
    listing_id: int
    charity_id: int
    joined_at: datetime.datetime
    status: str
    position: int  # computed from ordering (1 = next in line)

    model_config = ConfigDict(from_attributes=True)


class WaitlistPosition(BaseModel):
    """Returned after successfully joining the waitlist."""
    listing_id: int
    charity_id: int
    position: int


class WaitlistStatusUpdate(BaseModel):
    """Body sent by the Claim Service to update an entry's status."""
    status: str  # PROMOTED or CANCELLED
