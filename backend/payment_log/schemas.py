"""
Pydantic v2 schemas for the Payment Log Service.
"""
import datetime

from pydantic import BaseModel, Field

from models import PaymentStatus


class PaymentLogCreate(BaseModel):
    """Body for POST /logs — called by the Orchestrator after creating a PaymentIntent."""
    stripe_transaction_id : str   = Field(..., min_length=1, max_length=128)
    listing_id            : int   = Field(..., gt=0)
    listing_version       : int   = Field(..., ge=0)
    amount                : float = Field(..., gt=0)


class PaymentLogUpdate(BaseModel):
    """Body for PATCH /logs/{transaction_id} — updates the status only."""
    status: PaymentStatus


class PaymentLogResponse(BaseModel):
    """What the API returns for every log read/write operation."""
    model_config = {"from_attributes": True}

    id                    : int
    stripe_transaction_id : str
    listing_id            : int
    listing_version       : int
    status                : PaymentStatus
    amount                : float
    created_at            : datetime.datetime
    updated_at            : datetime.datetime | None
