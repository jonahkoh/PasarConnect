import datetime
import enum

from pydantic import BaseModel, Field


class ClaimStatus(str, enum.Enum):
    """Public status values returned by the Claim Orchestrator."""

    PENDING_COLLECTION = "PENDING_COLLECTION"
    AWAITING_VENDOR_APPROVAL = "AWAITING_VENDOR_APPROVAL"
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


# ── Waitlist schemas ───────────────────────────────────────────────────────────

class WaitlistJoin(BaseModel):
    """Body sent when a charity wants to join the waitlist."""
    charity_id: int = Field(..., gt=0)


class WaitlistPosition(BaseModel):
    """Returned after successfully joining the waitlist."""
    listing_id: int
    charity_id: int
    position: int  # 1 = next in line


class WaitlistListEntry(BaseModel):
    """One entry in the GET /waitlist response."""
    listing_id: int
    charity_id: int
    position: int
    status: str  # QUEUING (in window) or WAITING (post-window)


# ── Cancel claim schema ────────────────────────────────────────────────────────

class CancelClaimRequest(BaseModel):
    """Body sent when cancelling an active claim."""
    charity_id: int = Field(..., gt=0)  # must match the claim owner
