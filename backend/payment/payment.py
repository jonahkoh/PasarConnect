"""
Payment Service — Orchestrator.

This service has NO database of its own.  It coordinates three downstream
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
                                     

Workflow 1 — Intent Creation (POST /payments/intent)
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
from contextlib import asynccontextmanager

import grpc
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from math import isclose

import inventory_client
import payment_log_client
import publisher
from schemas import PaymentIntentRequest, StripeWebhookPayload

load_dotenv()

logger = logging.getLogger(__name__)

# ── Internal service URLs (injected via env vars in Docker) ───────────────────
STRIPE_WRAPPER_URL = os.getenv("STRIPE_WRAPPER_URL", "http://localhost:8004")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No DB to set up — this service is stateless.
    yield


app = FastAPI(title="PasarConnect — Payment Service", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "payment"}


# ── Helper: call an internal service and surface errors cleanly ───────────────

async def _post(client: httpx.AsyncClient, url: str, body: dict) -> dict:
    """
    POST to an internal service.  Raises HTTPException with the upstream
    status code so callers get a meaningful error instead of a 500.
    """
    response = await client.post(url, json=body, timeout=10.0)
    response.raise_for_status()
    return response.json()


def _payment_status_name(status_value: int) -> str:
    import payment_log_pb2

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
async def create_payment_intent(payload: PaymentIntentRequest):
    """
    Called by the UI when a charity selects a listing to purchase.

    Steps:
      1. Soft-lock the listing in Inventory (AVAILABLE → PENDING_PAYMENT).
      2. Ask the Stripe Wrapper to create a PaymentIntent.
      3. Tell the Payment Log to persist a PENDING record.
      4. Return the client_secret so the UI can render the Stripe payment form.
    """
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
            {"listing_id": payload.listing_id, "amount": payload.amount},
        )

    # Step 3 — Persist PENDING record in Payment Log via gRPC
    try:
        await payment_log_client.create_payment_log(
            transaction_id=intent["payment_intent_id"],
            listing_id=payload.listing_id,
            listing_version=new_version,
            amount=payload.amount,
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
    import payment_log_pb2

    log = await _fetch_payment_log_or_raise(payload.stripe_transaction_id)

    status_name = _payment_status_name(log.status)
    if status_name in ("SUCCESS", "COLLECTED", "REFUNDED"):
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

    # ── Step 2: Move to collection flow (PENDING_PAYMENT → PENDING_COLLECTION) ─
    try:
        new_version = await inventory_client.mark_listing_pending_collection(
            payload.listing_id, listing_version
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
            listing_id     = payload.listing_id,
            reason         = f"Inventory gRPC error: [{exc.code()}] {exc.details()}",
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
        listing_id     = payload.listing_id,
    )

    logger.info(
        "Payment fulfilled — transaction_id=%s listing_id=%s.",
        payload.stripe_transaction_id, payload.listing_id,
    )
    return {"status": "ok", "transaction_id": payload.stripe_transaction_id}


@app.post("/payments/{transaction_id}/approve")
async def approve_payment(transaction_id: str):
    import payment_log_pb2

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

    await publisher.publish_payment_success(
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
    import payment_log_pb2

    log = await _require_success_payment_log(transaction_id, action="rejected")

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

    await publisher.publish_payment_failure(
        transaction_id=transaction_id,
        listing_id=log.listing_id,
        reason="Payment manually rejected",
    )

    return {
        "status": "ok",
        "transaction_id": transaction_id,
        "new_status": "REFUNDED",
        "inventory_version": new_version,
    }


@app.post("/payments/{transaction_id}/approve")
async def approve_payment(transaction_id: str):
    import payment_log_pb2

    try:
        result = await payment_log_client.update_payment_status(
            transaction_id=transaction_id,
            new_status=payment_log_pb2.COLLECTED,
        )
    except grpc.aio.AioRpcError as exc:
        raise payment_log_client.map_payment_log_grpc_error(exc)

    try:
        new_version = await inventory_client.mark_listing_sold(
            listing_id=result.listing_id,
            expected_version=result.listing_version,
        )
    except grpc.aio.AioRpcError:
        raise HTTPException(status_code=503, detail="Inventory update failed after payment approval")

    await publisher.publish_payment_success(
        transaction_id=transaction_id,
        listing_id=result.listing_id,
    )

    return {
        "status": "ok",
        "transaction_id": transaction_id,
        "new_status": "COLLECTED",
        "inventory_version": new_version,
    }


@app.post("/payments/{transaction_id}/reject")
async def reject_payment(transaction_id: str):
    import payment_log_pb2

    try:
        result = await payment_log_client.update_payment_status(
            transaction_id=transaction_id,
            new_status=payment_log_pb2.REFUNDED,
        )
    except grpc.aio.AioRpcError as exc:
        raise payment_log_client.map_payment_log_grpc_error(exc)

    async with httpx.AsyncClient() as client:
        try:
            await _post(
                client,
                f"{STRIPE_WRAPPER_URL}/stripe/refund",
                {
                    "payment_intent_id": transaction_id,
                    "amount": result.amount,
                },
            )
        except httpx.HTTPStatusError:
            raise HTTPException(status_code=503, detail="Refund failed in Stripe Wrapper")

    try:
        new_version = await inventory_client.rollback_listing_to_available(
            listing_id=result.listing_id,
            expected_version=result.listing_version,
        )
    except grpc.aio.AioRpcError:
        raise HTTPException(status_code=503, detail="Inventory rollback failed after payment rejection")

    await publisher.publish_payment_failure(
        transaction_id=transaction_id,
        listing_id=result.listing_id,
        reason="Payment manually rejected",
    )

    return {
        "status": "ok",
        "transaction_id": transaction_id,
        "new_status": "REFUNDED",
        "inventory_version": new_version,
    }

