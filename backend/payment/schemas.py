"""
Pydantic v2 schemas for the Payment Service (Orchestrator).
"""
from pydantic import BaseModel, Field


class PaymentIntentRequest(BaseModel):
    """Sent by the UI when a charity wants to purchase a listing."""
    listing_id      : int   = Field(..., gt=0)
    listing_version : int   = Field(..., ge=0)
    amount          : float = Field(..., gt=0)


class StripeWebhookPayload(BaseModel):
    """
    Forwarded by the Stripe Wrapper when a payment_intent.succeeded event
    arrives from Stripe.  Includes the listing context needed for gRPC.
    """
    stripe_transaction_id : str   = Field(..., min_length=1, max_length=128)
    listing_id            : int   = Field(..., gt=0)
    amount                : float = Field(..., gt=0)
