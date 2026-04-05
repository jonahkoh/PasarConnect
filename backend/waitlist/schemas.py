import datetime

from pydantic import BaseModel, ConfigDict, Field


class WaitlistJoin(BaseModel):
    """Body sent when a charity wants to join the waitlist."""
    charity_id: int = Field(..., gt=0)
    status: str = "WAITING"  # WAITING (normal) or QUEUING (inside queue window)


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


class WaitlistResolveEntry(BaseModel):
    """One ranked entry in a queue resolution request."""
    entry_id: int
    rank: int
    score: int


class WaitlistResolve(BaseModel):
    """Body for POST /waitlist/{listing_id}/resolve."""
    entries: list[WaitlistResolveEntry]
