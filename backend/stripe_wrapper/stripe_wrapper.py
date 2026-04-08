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

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)

import stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PAYMENT_SERVICE_URL   = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8003")

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
    """
    try:
        intent = stripe.PaymentIntent.create(
            amount   = round(payload.amount * 100),   # Stripe expects integer cents
            currency = "sgd",
            metadata = {"listing_id": payload.listing_id},
        )
    except stripe.error.StripeError as exc:
        logger.error("Stripe PaymentIntent.create failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(getattr(exc, "user_message", None) or exc))
    return {"payment_intent_id": intent.id, "client_secret": intent.client_secret}


@app.post("/stripe/refund", response_model=RefundResponse)
async def issue_refund(payload: RefundRequest):
    """
    Issues a refund for a previously created PaymentIntent.

    In the compensating transaction flow, the Orchestrator calls this when
    the Inventory gRPC call fails after the customer has already been charged.
    """
    try:
        refund = stripe.Refund.create(payment_intent=payload.payment_intent_id)
    except stripe.error.StripeError as exc:
        logger.error("Stripe Refund.create failed for %s: %s", payload.payment_intent_id, exc)
        raise HTTPException(status_code=502, detail=str(getattr(exc, "user_message", None) or exc))
    return {"refund_id": refund.id, "status": refund.status}


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Receives raw Stripe webhook events, verifies the HMAC-SHA256 signature,
    and forwards payment_intent.succeeded to the payment service.

    Local testing with Stripe CLI:
        stripe listen --forward-to localhost:8004/stripe/webhook
    The CLI prints a whsec_... secret — set it as STRIPE_WEBHOOK_SECRET in .env.
    """
    if not STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET is not configured")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(body, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        logger.warning("Invalid Stripe webhook signature")
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if event["type"] == "payment_intent.succeeded":
        pi = event["data"]["object"]
        amount_dollars = pi["amount_received"] / 100.0   # cents → SGD dollars
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{PAYMENT_SERVICE_URL}/webhooks/stripe",
                    json={
                        "stripe_transaction_id": pi["id"],
                        "amount": amount_dollars,
                    },
                    timeout=10.0,
                )
                resp.raise_for_status()
                logger.info(
                    "Stripe webhook forwarded — pi=%s amount=%.2f",
                    pi["id"], amount_dollars,
                )
            except httpx.HTTPStatusError as exc:
                logger.error("Payment service rejected webhook: %s", exc)
                raise HTTPException(status_code=502, detail="Payment service failed to process webhook")

    return {"received": True}