"""
Payment Service — Orchestrator.

This service has NO database of its own.  It coordinates four downstream
services and owns the workflow logic only:

  ┌─────────────┐  HTTP   ┌──────────────────────┐      HTTP
  │  UI / Client│ ──────► │  Payment Orchestrator│────────────────────────────┐
  └─────────────┘         └──────┬──────┬────────┘                            │  
                                 │ gRPC │ HTTP                                │    
                    ┌────────────┘      └──────────────┐                      │              
                    ▼                                  ▼                      ▼  
          ┌──────────────────┐              ┌──────────────────┐    ┌──────────────────┐
          │  Inventory Svc   │              │  Stripe Wrapper  │    │  Payment Log Svc │
          └──────────────────┘              └──────────────────┘    └──────────────────┘
          ┌──────────────────┐
          │ Verification Svc │  (gRPC — user eligibility check)
          └──────────────────┘

Workflow 1 — Intent Creation (POST /payments/intent)
  0. gRPC  → Verification: check user standing (BANNED / noshow limit → 403)
  1. gRPC  → Inventory: soft lock listing (AVAILABLE → PENDING_PAYMENT)
  2. HTTP  → Stripe Wrapper: create PaymentIntent, get client_secret
  3. gRPC  → Payment Log: persist record with status=PENDING
  4. Return client_secret to UI

Workflow 2 — Webhook Fulfillment (POST /webhooks/stripe)
    1. gRPC  → Payment Log: idempotency + amount guardrail base data
    2. gRPC  → Inventory: move listing to pickup flow (PENDING_PAYMENT → PENDING_COLLECTION)
  3a. On gRPC failure — COMPENSATING TRANSACTION:
        HTTP → Stripe Wrapper: refund
                gRPC → Payment Log: set status=REFUNDED
        Publish payment.failure to RabbitMQ
        Return 503
  3b. On gRPC success:
        gRPC → Payment Log: set status=SUCCESS (payment completed)
        Publish payment.success to RabbitMQ
        Return 200
"""
import logging
import os
import datetime
from datetime import timedelta
from contextlib import asynccontextmanager

import grpc
import httpx
from dotenv import load_dotenv
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from shared.jwt_auth import verify_jwt_token

from math import isclose

import payment_log_pb2
import inventory_client
import payment_log_client
import publisher
import verification_client
from schemas import PaymentIntentRequest, PaymentNoShowRequest, StripeWebhookPayload, UserCancelRequest
from verification_client import UserNotEligibleError

load_dotenv()

logger = logging.getLogger(__name__)

# ── Internal service URLs (injected via env vars in Docker) ───────────────────
STRIPE_WRAPPER_URL   = os.getenv("STRIPE_WRAPPER_URL",   "http://localhost:8004")
PAYMENT_LOG_HTTP_URL = os.getenv("PAYMENT_LOG_HTTP_URL", "http://payment-log-service:8005")

# Mirrors the same env var used by the Claim Service — must stay in sync.
QUEUE_WINDOW_MINUTES = float(os.getenv("QUEUE_WINDOW_MINUTES", "5"))
QUEUE_WINDOW = timedelta(minutes=QUEUE_WINDOW_MINUTES)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No DB to set up — this service is stateless.
    yield


app = FastAPI(title="PasarConnect — Payment Service", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "payment"}


# ── Helper: call an internal service and surface errors cleanly ───────────────

CANCELLATION_WINDOW_MINUTES = float(os.getenv("CANCELLATION_WINDOW_MINUTES", "1"))  # production intent: 10 mins
VENDOR_WARNING_MINUTES      = float(os.getenv("VENDOR_WARNING_MINUTES",      "1"))  # production intent: 30 mins


def _minutes_since_payment(log) -> float:
    """
    Returns minutes elapsed since the payment was confirmed (moved to SUCCESS).
    Uses updated_at (set by the SUCCESS webhook transition) with created_at as fallback.
    """
    ts_str = log.updated_at if log.updated_at else log.created_at
    if not ts_str:
        return 0.0
    try:
        paid_at = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0.0
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    if paid_at.tzinfo is None:
        paid_at = paid_at.replace(tzinfo=datetime.timezone.utc)
    return (now - paid_at).total_seconds() / 60


async def _post(client: httpx.AsyncClient, url: str, body: dict) -> dict:
    """
    POST to an internal service.  Raises HTTPException with the upstream
    status code so callers get a meaningful error instead of a 500.
    """
    response = await client.post(url, json=body, timeout=10.0)
    response.raise_for_status()
    return response.json()


def _payment_status_name(status_value: int) -> str:
    return payment_log_pb2.PaymentStatus.Name(status_value)


async def _fetch_payment_log_or_raise(transaction_id: str):
    try:
        return await payment_log_client.get_payment_log(transaction_id)
    except grpc.aio.AioRpcError as exc:
        raise payment_log_client.map_payment_log_grpc_error(exc)


async def _require_success_payment_log(transaction_id: str, action: str):
    log = await _fetch_payment_log_or_raise(transaction_id)
    if _payment_status_name(log.status) != "SUCCESS":
        raise HTTPException(status_code=409, detail=f"Only SUCCESS payments can be {action}")
    return log


# ── Workflow 1: Intent Creation ───────────────────────────────────────────────

@app.post("/payments/intent", status_code=201)
async def create_payment_intent(
    payload: PaymentIntentRequest,
    token_payload: Annotated[dict, Depends(verify_jwt_token)],
):
    """
    Called by the UI when a public user selects a listing to purchase.

    Steps:
      0. Verify the user's standing with the Verification Service.
      1. Soft-lock the listing in Inventory (AVAILABLE → PENDING_PAYMENT).
      2. Ask the Stripe Wrapper to create a PaymentIntent.
      3. Tell the Payment Log to persist a PENDING record.
      4. Return the client_secret so the UI can render the Stripe payment form.
    """
    # Identity is taken from the JWT sub claim — never from the request body.
    user_id = int(token_payload["sub"])

    # Step 0 — Verify user eligibility before touching inventory
    try:
        await verification_client.verify_public_user(user_id, payload.listing_id)
    except UserNotEligibleError as exc:
        raise HTTPException(status_code=403, detail=f"User ineligible: {exc.reason}")

    # Step 0b — Block purchase while the charity queue window is active
    listing_price = 0.0
    try:
        listing_info = await inventory_client.get_listing(payload.listing_id)
        listing_price = listing_info.price  # 0.0 means no price set
        listed_at_str = listing_info.listed_at
        if listed_at_str:
            listed_at = datetime.datetime.fromisoformat(listed_at_str)
            if listed_at.tzinfo is None:
                listed_at = listed_at.replace(tzinfo=datetime.timezone.utc)
            window_closes_at = listed_at + QUEUE_WINDOW
            if datetime.datetime.now(tz=datetime.timezone.utc) < window_closes_at:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "queue_window_active",
                        "message": "This listing is reserved for charities during the queue window.",
                        "window_closes_at": window_closes_at.isoformat(),
                    },
                )
    except HTTPException:
        raise
    except Exception as exc:
        # Fail-open: if inventory is unreachable here, let the lock attempt in Step 1 fail properly
        logger.warning("Queue-window pre-check failed for listing %s (fail-open): %s", payload.listing_id, exc)

    if listing_price <= 0:
        raise HTTPException(
            status_code=422,
            detail="Listing has no price set. Vendor must set a price before it can be purchased.",
        )

    # Step 1 — Soft lock in Inventory
    # If the listing is already taken, gRPC returns ABORTED (version mismatch)
    # or NOT_FOUND — we let those propagate as 409 / 404 via the exception handler.
    try:
        new_version = await inventory_client.lock_listing_pending_payment(
            payload.listing_id, payload.listing_version
        )
    except grpc.aio.AioRpcError as exc:
        code = exc.code()
        if code == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Listing not found.")
        if code == grpc.StatusCode.ABORTED:
            raise HTTPException(status_code=409, detail="Listing is no longer available.")
        raise HTTPException(status_code=503, detail="Inventory service unavailable.")

    async with httpx.AsyncClient() as client:
        # Step 2 — Create PaymentIntent via Stripe Wrapper
        intent = await _post(
            client,
            f"{STRIPE_WRAPPER_URL}/stripe/intent",
            {"listing_id": payload.listing_id, "amount": listing_price},
        )

    # Step 3 — Persist PENDING record in Payment Log via gRPC
    try:
        await payment_log_client.create_payment_log(
            transaction_id=intent["payment_intent_id"],
            listing_id=payload.listing_id,
            listing_version=new_version,
            amount=listing_price,
            user_id=user_id,
        )
    except grpc.aio.AioRpcError as exc:
        raise payment_log_client.map_payment_log_grpc_error(exc)

    # Step 4 — Return client_secret to the UI
    return {"client_secret": intent["client_secret"]}


# ── Workflow 2: Webhook Fulfillment ───────────────────────────────────────────

@app.post("/webhooks/stripe")
async def stripe_webhook(payload: StripeWebhookPayload):
    """
    Called by the Stripe Wrapper when a payment_intent.succeeded event arrives.

    Steps:
    1. Idempotency check — if already SUCCESS/COLLECTED/REFUNDED, return 200 immediately.
    2. Guardrail check — webhook amount must equal intent amount from Payment Log.
    3. Move listing in Inventory (PENDING_PAYMENT → PENDING_COLLECTION).
      3a. gRPC failure → Compensating Transaction (refund + log + publish).
      3b. gRPC success → update log to SUCCESS and publish payment.success.
    """
    # ── Step 1: Idempotency guard ─────────────────────────────────────────
    log = await _fetch_payment_log_or_raise(payload.stripe_transaction_id)

    status_name = _payment_status_name(log.status)
    if status_name in ("SUCCESS", "COLLECTED", "REFUNDED", "FORFEITED"):
        logger.info(
            "Duplicate webhook — transaction_id=%s already %s.",
            payload.stripe_transaction_id, status_name,
        )
        return {"status": "already_processed"}

    # Guardrail: webhook amount must match the amount persisted at intent creation.
    if not isclose(payload.amount, log.amount, abs_tol=1e-6):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "amount_mismatch",
                "message": "Webhook amount does not match intent amount.",
                "expected_amount": log.amount,
                "received_amount": payload.amount,
                "transaction_id": payload.stripe_transaction_id,
            },
        )

    listing_version = log.listing_version

    # ── Step 2: Move to collection flow (PENDING_PAYMENT → SOLD_PENDING_COLLECTION) ─
    try:
        new_version = await inventory_client.mark_listing_sold_pending_collection(
            log.listing_id, listing_version
        )

    except grpc.aio.AioRpcError as exc:
        # ── COMPENSATING TRANSACTION ──────────────────────────────────────
        # Money left the customer's account but inventory cannot be updated.
        # We must reverse the charge and record the failure before returning.
        logger.error(
            "Inventory gRPC failed for transaction_id=%s: [%s] %s",
            payload.stripe_transaction_id, exc.code(), exc.details(),
        )

        # Step 3a-i: Issue refund via Stripe Wrapper
        refund_ok = False
        async with httpx.AsyncClient() as client:
            try:
                await _post(
                    client,
                    f"{STRIPE_WRAPPER_URL}/stripe/refund",
                    {
                        "payment_intent_id": payload.stripe_transaction_id,
                        "amount"           : payload.amount,
                    },
                )
                refund_ok = True
            except httpx.HTTPStatusError as refund_exc:
                logger.error(
                    "Stripe Wrapper refund failed for transaction_id=%s: %s",
                    payload.stripe_transaction_id, refund_exc,
                )

        # Step 3a-i-b: Roll inventory back PENDING_PAYMENT → AVAILABLE.
        # The mark_listing_sold_pending_collection call FAILED so the listing
        # is still at PENDING_PAYMENT — we must free it.
        try:
            await inventory_client.rollback_listing_to_available(
                log.listing_id, log.listing_version
            )
        except grpc.aio.AioRpcError as inv_exc:
            logger.error(
                "Inventory rollback to AVAILABLE failed for transaction_id=%s: [%s] %s",
                payload.stripe_transaction_id, inv_exc.code(), inv_exc.details(),
            )

        # Step 3a-ii: Update the log record to REFUNDED (or FAILED)
        new_status = payment_log_pb2.REFUNDED if refund_ok else payment_log_pb2.FAILED
        try:
            await payment_log_client.update_payment_status_with_version(
                transaction_id=payload.stripe_transaction_id,
                new_status=new_status,
            )
        except grpc.aio.AioRpcError:
            # Log update failed — record is stuck at PENDING and requires manual ops.
            logger.error(
                "Payment Log update to %s failed for transaction_id=%s.",
                payment_log_pb2.PaymentStatus.Name(new_status), payload.stripe_transaction_id,
            )

        # Step 3a-iii: Publish failure event for Auditor Service
        await publisher.publish_payment_failure(
            transaction_id = payload.stripe_transaction_id,
            listing_id     = log.listing_id,
            reason         = f"Inventory gRPC error: [{exc.code()}] {exc.details()}",
        )

        # Notify the buyer via their private channel only when a refund was issued.
        if refund_ok:
            await publisher.publish_payment_refunded(
                transaction_id = payload.stripe_transaction_id,
                listing_id     = log.listing_id,
                user_id        = log.user_id,
                reason         = "Inventory service unavailable — your payment has been refunded automatically.",
            )

        raise HTTPException(
            status_code=503,
            detail={
                "error"          : "inventory_unavailable",
                "message"        : "Payment reversed — inventory could not be updated.",
                "transaction_id" : payload.stripe_transaction_id,
                "refunded"       : refund_ok,
            },
        )

    # ── Step 3b: Success path ──────────────────────────────────────────────
    try:
        await payment_log_client.update_payment_status_with_version(
            transaction_id=payload.stripe_transaction_id,
            new_status=payment_log_pb2.SUCCESS,
            listing_version=new_version,
        )
    except grpc.aio.AioRpcError as exc:
        raise payment_log_client.map_payment_log_grpc_error(exc)

    await publisher.publish_payment_success(
        transaction_id = payload.stripe_transaction_id,
        listing_id     = log.listing_id,
        user_id        = log.user_id,
    )

    logger.info(
        "Payment fulfilled — transaction_id=%s listing_id=%s status=SOLD_PENDING_COLLECTION.",
        payload.stripe_transaction_id, log.listing_id,
    )
    return {"status": "ok", "transaction_id": payload.stripe_transaction_id}


@app.get("/payments/history")
async def get_payment_history(
    token_payload: Annotated[dict, Depends(verify_jwt_token)],
):
    """
    Returns the authenticated user's full purchase history from the Payment Log service.
    Ordered newest-first.
    """
    user_id = int(token_payload["sub"])
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{PAYMENT_LOG_HTTP_URL}/user-history/{user_id}",
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Payment Log service error: {exc.response.status_code}",
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail="Payment Log service unavailable")
    return response.json()


@app.post("/payments/{transaction_id}/arrived", status_code=200)
async def buyer_arrived(
    transaction_id: str,
    token_payload: Annotated[dict, Depends(verify_jwt_token)],
):
    """
    Buyer is on-site and ready for item collection.
    Publishes payment.arrived so the vendor is notified via Socket.io.
    Only valid when the payment is in SUCCESS state.
    """
    user_id = int(token_payload["sub"])
    log = await _fetch_payment_log_or_raise(transaction_id)

    if _payment_status_name(log.status) != "SUCCESS":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot signal arrival when payment status is {_payment_status_name(log.status)}",
        )

    if user_id != log.user_id:
        raise HTTPException(status_code=403, detail="Not the transaction owner")

    await publisher.publish_payment_arrived(
        transaction_id=transaction_id,
        listing_id=log.listing_id,
        user_id=user_id,
    )

    logger.info(
        "Buyer arrived signal — transaction_id=%s listing_id=%s user_id=%s",
        transaction_id, log.listing_id, user_id,
    )
    return {"status": "ok", "transaction_id": transaction_id}


@app.delete("/payments/{transaction_id}/intent", status_code=200)
async def abandon_payment_intent(
    transaction_id: str,
    body: UserCancelRequest,
):
    """
    Abandon a PENDING payment intent before Stripe confirmation.

    Called when the user exits the payment form without paying (clicks
    \u201cCancel and return to cart\u201d after intents were already created).

    Flow:
      1. Fetch PENDING payment log.
      2. Roll inventory back PENDING_PAYMENT \u2192 AVAILABLE.
      3. Mark payment log as REFUNDED (no money was taken, so no real refund needed).
    """
    log = await _fetch_payment_log_or_raise(transaction_id)

    status_name = _payment_status_name(log.status)
    if status_name not in ("PENDING", "REFUNDED"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot abandon a payment that is already {status_name}",
        )

    if body.user_id != log.user_id:
        raise HTTPException(status_code=403, detail="user_id does not match the transaction owner")

    # Roll back PENDING_PAYMENT → AVAILABLE (best-effort; idempotent recovery for stuck listings)
    try:
        await inventory_client.rollback_listing_to_available(log.listing_id, log.listing_version)
    except grpc.aio.AioRpcError as exc:
        logger.error(
            "Inventory rollback failed on abandon for transaction_id=%s: [%s] %s",
            transaction_id, exc.code(), exc.details(),
        )

    # Mark log REFUNDED only if still PENDING — REFUNDED means the compensating tx already ran
    if status_name == "PENDING":
        try:
            await payment_log_client.update_payment_status_with_version(
                transaction_id=transaction_id,
                new_status=payment_log_pb2.REFUNDED,
            )
        except grpc.aio.AioRpcError as exc:
            raise payment_log_client.map_payment_log_grpc_error(exc)

    return {"status": "abandoned", "transaction_id": transaction_id}


@app.post("/payments/{transaction_id}/approve")
async def approve_payment(transaction_id: str):
    log = await _require_success_payment_log(transaction_id, action="approved")

    try:
        new_version = await inventory_client.mark_listing_sold(
            listing_id=log.listing_id,
            expected_version=log.listing_version,
        )
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.ABORTED:
            raise HTTPException(status_code=409, detail="Listing version conflict. Re-fetch listing and retry")
        if exc.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Listing not found")
        raise HTTPException(status_code=503, detail="Inventory update failed after payment approval")

    try:
        await payment_log_client.update_payment_status_with_version(
            transaction_id=transaction_id,
            new_status=payment_log_pb2.COLLECTED,
            listing_version=new_version,
        )
    except grpc.aio.AioRpcError as exc:
        raise payment_log_client.map_payment_log_grpc_error(exc)

    # Use a separate collected event — payment.success was already fired by the
    # webhook when the buyer's card was charged.  Firing it again here would
    # cause duplicate "Payment received" toasts in the vendor dashboard.
    await publisher.publish_payment_collected(
        transaction_id=transaction_id,
        listing_id=log.listing_id,
    )

    return {
        "status": "ok",
        "transaction_id": transaction_id,
        "new_status": "COLLECTED",
        "inventory_version": new_version,
    }


@app.post("/payments/{transaction_id}/reject")
async def reject_payment(transaction_id: str):
    """
    Vendor-initiated rejection.  User is always refunded.
    A warning is included in the response if the vendor rejects more than
    30 minutes after the payment was confirmed.
    """
    log = await _require_success_payment_log(transaction_id, action="rejected")
    minutes_elapsed = _minutes_since_payment(log)
    vendor_warning  = minutes_elapsed > VENDOR_WARNING_MINUTES

    async with httpx.AsyncClient() as client:
        try:
            await _post(
                client,
                f"{STRIPE_WRAPPER_URL}/stripe/refund",
                {
                    "payment_intent_id": transaction_id,
                    "amount": log.amount,
                },
            )
        except httpx.HTTPStatusError:
            raise HTTPException(status_code=503, detail="Refund failed in Stripe Wrapper")

    try:
        await payment_log_client.update_payment_status_with_version(
            transaction_id=transaction_id,
            new_status=payment_log_pb2.REFUNDED,
        )
    except grpc.aio.AioRpcError as exc:
        raise payment_log_client.map_payment_log_grpc_error(exc)

    try:
        new_version = await inventory_client.rollback_listing_to_available(
            listing_id=log.listing_id,
            expected_version=log.listing_version,
        )
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.ABORTED:
            raise HTTPException(
                status_code=409,
                detail="Refund succeeded but listing version changed before rollback. Manual inventory recovery required",
            )
        if exc.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Refund succeeded but listing no longer exists")
        raise HTTPException(status_code=503, detail="Refund succeeded but inventory rollback failed")

    await publisher.publish_payment_refunded(
        transaction_id=transaction_id,
        listing_id=log.listing_id,
        user_id=log.user_id,
        reason="Payment manually rejected by vendor",
    )

    return {
        "status": "ok",
        "transaction_id": transaction_id,
        "new_status": "REFUNDED",
        "inventory_version": new_version,
        **({
            "vendor_warning": (
                f"Rejection occurred {round(minutes_elapsed, 1)} minutes after payment — "
                "exceeds the expected 30-minute fulfilment window."
            )
        } if vendor_warning else {}),
    }


@app.post("/payments/{transaction_id}/cancel", status_code=200)
async def cancel_payment(transaction_id: str, body: UserCancelRequest):
    """
    User-initiated cancellation.  Only permitted within 10 minutes of payment confirmation.
    After the window closes the endpoint returns 409 and the payment is not refunded.
    """
    log = await _require_success_payment_log(transaction_id, action="cancelled")

    if body.user_id != log.user_id:
        raise HTTPException(status_code=403, detail="user_id does not match the transaction owner")

    minutes_elapsed = _minutes_since_payment(log)

    if minutes_elapsed > CANCELLATION_WINDOW_MINUTES:
        # Record the late-cancel attempt in Verification Service (best-effort).
        await verification_client.record_user_late_cancel(
            user_id=body.user_id,
            transaction_id=transaction_id,
        )
        # Mark payment as FORFEITED — no refund, no inventory release.
        try:
            await payment_log_client.update_payment_status_with_version(
                transaction_id=transaction_id,
                new_status=payment_log_pb2.FORFEITED,
            )
        except grpc.aio.AioRpcError as exc:
            raise payment_log_client.map_payment_log_grpc_error(exc)
        # Rollback inventory to AVAILABLE (best-effort — listing stays locked if this fails).
        try:
            await inventory_client.rollback_listing_to_available(
                listing_id=log.listing_id,
                expected_version=log.listing_version,
            )
        except grpc.aio.AioRpcError:
            logger.error(
                "Inventory rollback failed on late cancel for transaction_id=%s", transaction_id
            )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "cancellation_window_expired",
                "message": (
                    f"Cancellation window has expired. "
                    f"You had {CANCELLATION_WINDOW_MINUTES} minutes after payment to cancel. "
                    f"{round(minutes_elapsed, 1)} minutes have elapsed."
                ),
                "minutes_elapsed": round(minutes_elapsed, 1),
                "window_minutes": CANCELLATION_WINDOW_MINUTES,
            },
        )

    # Within window — refund and rollback
    async with httpx.AsyncClient() as client:
        try:
            await _post(
                client,
                f"{STRIPE_WRAPPER_URL}/stripe/refund",
                {"payment_intent_id": transaction_id, "amount": log.amount},
            )
        except httpx.HTTPStatusError:
            raise HTTPException(status_code=503, detail="Refund failed in Stripe Wrapper")

    try:
        await payment_log_client.update_payment_status_with_version(
            transaction_id=transaction_id,
            new_status=payment_log_pb2.REFUNDED,
        )
    except grpc.aio.AioRpcError as exc:
        raise payment_log_client.map_payment_log_grpc_error(exc)

    try:
        new_version = await inventory_client.rollback_listing_to_available(
            listing_id=log.listing_id,
            expected_version=log.listing_version,
        )
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.ABORTED:
            raise HTTPException(
                status_code=409,
                detail="Refund succeeded but listing version changed before rollback. Manual inventory recovery required",
            )
        if exc.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Refund succeeded but listing no longer exists")
        raise HTTPException(status_code=503, detail="Refund succeeded but inventory rollback failed")

    await publisher.publish_payment_cancelled(
        transaction_id=transaction_id,
        listing_id=log.listing_id,
        user_id=log.user_id,
    )

    return {
        "status": "ok",
        "transaction_id": transaction_id,
        "new_status": "REFUNDED",
        "minutes_elapsed": round(minutes_elapsed, 1),
        "inventory_version": new_version,
    }


@app.post("/payments/{transaction_id}/noshow", status_code=200)
async def noshow_payment(transaction_id: str, body: PaymentNoShowRequest):
    """
    Called by the vendor when a public user fails to collect their order.

    If the no-show is reported within 10 minutes of payment, the user is refunded
    (they may genuinely be running late).  After the window, no refund is issued
    (user forfeits their payment) and the status is set to FORFEITED.

    Flow:
      1. Fetch payment log — validates transaction exists and is SUCCESS.
      2. Determine refund eligibility (10-minute window).
      3a. Within window  → refund + REFUNDED.
      3b. Past window    → no refund + FORFEITED.
      4. Rollback Inventory → AVAILABLE (always).
      5. Record user no-show in Verification Service (always, best-effort).
      6. Publish payment.failure event.
    """
    log = await _require_success_payment_log(transaction_id, action="marked as no-show")

    if body.user_id != log.user_id:
        raise HTTPException(status_code=403, detail="user_id does not match the transaction owner")

    minutes_elapsed = _minutes_since_payment(log)
    within_window   = minutes_elapsed <= CANCELLATION_WINDOW_MINUTES

    if within_window:
        # Step 3a — Refund the user
        async with httpx.AsyncClient() as client:
            try:
                await _post(
                    client,
                    f"{STRIPE_WRAPPER_URL}/stripe/refund",
                    {"payment_intent_id": transaction_id, "amount": log.amount},
                )
            except httpx.HTTPStatusError:
                raise HTTPException(status_code=503, detail="Refund failed in Stripe Wrapper")

        new_log_status = payment_log_pb2.REFUNDED
    else:
        # Step 3b — Past cancellation window, no refund
        new_log_status = payment_log_pb2.FORFEITED
        logger.info(
            "No-show after window — no refund issued for transaction_id=%s (%.1f min elapsed)",
            transaction_id, minutes_elapsed,
        )

    # Update Payment Log
    try:
        await payment_log_client.update_payment_status_with_version(
            transaction_id=transaction_id,
            new_status=new_log_status,
        )
    except grpc.aio.AioRpcError as exc:
        raise payment_log_client.map_payment_log_grpc_error(exc)

    # Rollback Inventory → AVAILABLE (regardless of refund)
    try:
        await inventory_client.rollback_listing_to_available(
            listing_id=log.listing_id,
            expected_version=log.listing_version,
        )
    except grpc.aio.AioRpcError:
        logger.error("Inventory rollback failed for noshow transaction_id=%s", transaction_id)

    # Record user no-show in Verification Service (best-effort)
    await verification_client.record_user_noshow(
        user_id=body.user_id,
        transaction_id=transaction_id,
    )

    # Publish typed outcome event so the notification layer can show the correct message.
    if within_window:
        await publisher.publish_payment_refunded(
            transaction_id=transaction_id,
            listing_id=log.listing_id,
            user_id=log.user_id,
            reason="No-show recorded — refund issued (within leniency window)",
        )
    else:
        await publisher.publish_payment_forfeited(
            transaction_id=transaction_id,
            listing_id=log.listing_id,
            user_id=log.user_id,
        )

    return {
        "status": "ok",
        "transaction_id": transaction_id,
        "user_id": body.user_id,
        "noshow_recorded": True,
        "refunded": within_window,
        "new_status": "REFUNDED" if within_window else "FORFEITED",
        "minutes_elapsed": round(minutes_elapsed, 1),
    }

