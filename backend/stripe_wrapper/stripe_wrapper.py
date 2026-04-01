"""
Stripe Wrapper Service — Vendor Abstraction Layer.

WHY THIS SERVICE EXISTS:
  The Orchestrator should never talk directly to Stripe.  This wrapper
  translates our internal HTTP requests into Stripe API calls (or mock
  equivalents) and returns a clean, Stripe-agnostic response.

  If we switch to a different payment provider (e.g. Adyen, Braintree),
  we replace only this file.  The Orchestrator is untouched.

HOW TO SWAP IN THE REAL STRIPE SDK:
  1. pip install stripe
  2. Set STRIPE_SECRET_KEY in your .env
  3. In create_intent() replace the mock block with:

        intent = stripe.PaymentIntent.create(
            amount   = int(amount * 100),   # Stripe expects cents
            currency = "sgd",
            metadata = {"listing_id": listing_id},
        )
        return {"payment_intent_id": intent.id, "client_secret": intent.client_secret}

  4. In issue_refund() replace the mock block with:

        refund = stripe.Refund.create(payment_intent=payment_intent_id)
        return {"refund_id": refund.id, "status": refund.status}

  Function signatures stay identical — the Orchestrator requires zero changes.

ENDPOINTS (internal only — not exposed to the public internet):
  POST /stripe/intent  — create a PaymentIntent, return client_secret
  POST /stripe/refund  — issue a Refund for a PaymentIntent
"""
import logging
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)

# Uncomment and set when switching to the real Stripe SDK:
# import stripe
# stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

app = FastAPI(title="PasarConnect — Stripe Wrapper Service")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "stripe-wrapper"}


# ── Request/Response schemas ──────────────────────────────────────────────────

class IntentRequest(BaseModel):
    """What the Orchestrator sends to create a PaymentIntent."""
    listing_id : int   = Field(..., gt=0)
    amount     : float = Field(..., gt=0)


class IntentResponse(BaseModel):
    """Returned to the Orchestrator after a PaymentIntent is created."""
    payment_intent_id : str   # stored in Payment Log as stripe_transaction_id
    client_secret     : str   # passed through to the UI to render Stripe's form


class RefundRequest(BaseModel):
    """What the Orchestrator sends to reverse a charge."""
    payment_intent_id : str   = Field(..., min_length=1)
    amount            : float = Field(..., gt=0)


class RefundResponse(BaseModel):
    """Returned to the Orchestrator after a refund is issued."""
    refund_id : str
    status    : str   # "succeeded" in mock mode


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/stripe/intent", response_model=IntentResponse, status_code=201)
async def create_intent(payload: IntentRequest):
    """
    Creates a Stripe PaymentIntent.

    Mock behaviour: generates a fake payment_intent_id and client_secret.
    The Orchestrator stores the payment_intent_id as the canonical
    transaction identifier in the Payment Log.
    """
    # ── MOCK (replace with real stripe.PaymentIntent.create() call) ──────────
    fake_id     = f"pi_mock_{uuid.uuid4().hex[:16]}"
    fake_secret = f"{fake_id}_secret_{uuid.uuid4().hex[:8]}"

    logger.info(
        "MOCK STRIPE: Created PaymentIntent %s for listing_id=%s amount=%.2f",
        fake_id, payload.listing_id, payload.amount,
    )
    return IntentResponse(payment_intent_id=fake_id, client_secret=fake_secret)


@app.post("/stripe/refund", response_model=RefundResponse)
async def issue_refund(payload: RefundRequest):
    """
    Issues a refund for a previously created PaymentIntent.

    In the compensating transaction flow, the Orchestrator calls this when
    the Inventory gRPC call fails after the customer has already been charged.

    Mock behaviour: always returns status="succeeded".
    If this endpoint itself fails (5xx), the Orchestrator catches the error,
    marks the transaction as FAILED, and raises a 503 to alert ops.
    """
    # ── MOCK (replace with real stripe.Refund.create() call) ─────────────────
    fake_refund_id = f"re_mock_{uuid.uuid4().hex[:16]}"

    logger.info(
        "MOCK STRIPE: Refund %s issued for payment_intent=%s amount=%.2f",
        fake_refund_id, payload.payment_intent_id, payload.amount,
    )
    return RefundResponse(refund_id=fake_refund_id, status="succeeded")
