"""
Pydantic v2 schemas for the Payment Service (Orchestrator).
"""
from pydantic import BaseModel, Field


class PaymentIntentRequest(BaseModel):
    """Sent by the UI when a public user wants to purchase a listing."""
    user_id         : int   = Field(..., gt=0)
    listing_id      : int   = Field(..., gt=0)
    listing_version : int   = Field(..., ge=0)
    amount          : float = Field(..., gt=0)


class PaymentNoShowRequest(BaseModel):
    """Sent by the vendor when a public user fails to collect their order."""
    user_id : int = Field(..., gt=0)


class UserCancelRequest(BaseModel):
    """Sent by the user to cancel a payment within the 10-minute cancellation window."""
    user_id : int = Field(..., gt=0)


class StripeWebhookPayload(BaseModel):
    """
    Forwarded by the Stripe Wrapper when a payment_intent.succeeded event
    arrives from Stripe.  Includes the listing context needed for gRPC.
    """
    stripe_transaction_id : str   = Field(..., min_length=1, max_length=128)
    listing_id            : int   = Field(..., gt=0)
    amount                : float = Field(..., gt=0)
