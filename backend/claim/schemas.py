import datetime
from pydantic import BaseModel
from models import ClaimStatus


class ClaimCreate(BaseModel):
    """What the client sends when creating a claim."""

    listing_id      : int
    charity_id      : int
    listing_version : int   # version the charity last read — used for optimistic locking


class ClaimResponse(BaseModel):
    """What the API returns after a claim is created."""

    model_config = {"from_attributes": True}

    id              : int
    listing_id      : int
    charity_id      : int
    status          : ClaimStatus
    listing_version : int
    created_at      : datetime.datetime
