"""
Claim Service — Orchestrator.

Coordinates the claim workflow across:
  Verification Service  (gRPC)  — charity eligibility + quota
  Inventory Service     (gRPC)  — optimistic-lock status transitions
  Claim Log Service     (HTTP)  — persistence
  RabbitMQ              (AMQP)  — async event fan-out
  Waitlist DB           (PostgreSQL) — charity queue per listing
"""
import logging
import os
from contextlib import asynccontextmanager
import verification_client


import grpc
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

import inventory_client
import publisher
import waitlist_router
from schemas import ClaimCreate, ClaimResponse, CancelClaimRequest
from waitlist_db import init_db
from waitlist_router import try_promote_next

load_dotenv()

logger = logging.getLogger(__name__)

CLAIM_LOG_URL = os.getenv("CLAIM_LOG_URL", "http://localhost:8006")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()   # create waitlist_entries table if it doesn't exist
    yield


app = FastAPI(title="PasarConnect — Claim Service", lifespan=lifespan)
app.include_router(waitlist_router.router)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "claim"}


async def _post(client: httpx.AsyncClient, url: str, body: dict) -> dict:
    response = await client.post(url, json=body, timeout=10.0)
    response.raise_for_status()
    return response.json()


@app.post("/claims", response_model=ClaimResponse, status_code=201)
async def create_claim(body: ClaimCreate):
    # 1) Verify eligibility via Verification Service (gRPC quota check).
    valid, reason = await verification_client.verify_charity_eligibility(body.charity_id, body.listing_id)
    if not valid:
        raise HTTPException(status_code=403, detail=reason)

    

    # 2) Soft lock listing in Inventory.
    try:
        new_version = await inventory_client.lock_listing_pending_collection(
            listing_id=body.listing_id,
            expected_version=body.listing_version,
        )
    except grpc.aio.AioRpcError as exc:
        code = exc.code()
        if code == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Listing not found")
        if code == grpc.StatusCode.ABORTED:
            raise HTTPException(status_code=409, detail="Listing already claimed — please refresh")
        raise HTTPException(status_code=503, detail="Inventory service unavailable")

    # 3) Persist to Claim Log service. If this fails, rollback inventory lock.
    try:
        async with httpx.AsyncClient() as client:
            claim_record = await _post(
                client,
                f"{CLAIM_LOG_URL}/logs",
                {
                    "listing_id": body.listing_id,
                    "charity_id": body.charity_id,
                    "listing_version": new_version,
                    "status": "PENDING_COLLECTION",
                },
            )
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error(
            "Claim Log handoff failed after inventory lock listing_id=%s version=%s: %s",
            body.listing_id,
            new_version,
            exc,
        )

        rollback_ok = False
        try:
            await inventory_client.rollback_listing_to_available(body.listing_id, new_version)
            rollback_ok = True
        except grpc.aio.AioRpcError as rollback_exc:
            logger.error(
                "Rollback failed for listing_id=%s version=%s: [%s] %s",
                body.listing_id,
                new_version,
                rollback_exc.code(),
                rollback_exc.details(),
            )

        await publisher.publish_claim_failure(
            listing_id=body.listing_id,
            charity_id=body.charity_id,
            reason=f"Claim log handoff failed: {exc}",
        )

        raise HTTPException(
            status_code=503,
            detail={
                "error": "claim_log_unavailable",
                "message": "Claim could not be finalized.",
                "listing_id": body.listing_id,
                "inventory_rollback_succeeded": rollback_ok,
            },
        )

    # 4) Publish success event (best effort).
    await publisher.publish_claim_success(
        claim_id=claim_record["id"],
        listing_id=claim_record["listing_id"],
        charity_id=claim_record["charity_id"],
    )

    return claim_record


@app.delete("/claims/{claim_id}", status_code=204)
async def cancel_claim(claim_id: int, body: CancelClaimRequest):
    """
    Cancel an active PENDING_COLLECTION claim.

    Flow:
      1. Fetch claim from Claim Log — get listing_id + current listing_version.
      2. Validate: caller must be the claim owner, claim must be PENDING_COLLECTION.
      3. Rollback Inventory: PENDING_COLLECTION → AVAILABLE  (returns v_available).
      4. Mark claim CANCELLED in Claim Log.
      5. Walk waitlist in FIFO order:
           a. Verify next charity (quota + legal check via Verification Service).
           b. If eligible: lock Inventory AVAILABLE → PENDING_COLLECTION (v_available → v_new),
              create a new claim log entry, mark waitlist entry PROMOTED,
              publish claim.waitlist.promoted → Notification Service WebSockets the charity.
           c. If ineligible: mark CANCELLED, try next charity.
           d. If queue is exhausted: publish claim.cancelled (item is now freely claimable).
    """
    # 1. Fetch claim record
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CLAIM_LOG_URL}/logs/{claim_id}", timeout=10.0)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Claim not found")
        resp.raise_for_status()
        claim = resp.json()

    # 2. Validate ownership and status
    if claim["charity_id"] != body.charity_id:
        raise HTTPException(status_code=403, detail="Cannot cancel another charity's claim")
    if claim["status"] != "PENDING_COLLECTION":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel a claim with status '{claim['status']}'",
        )

    listing_id      = claim["listing_id"]
    listing_version = claim["listing_version"]

    # 3. Rollback Inventory: PENDING_COLLECTION → AVAILABLE  (v → v+1)
    try:
        available_version = await inventory_client.rollback_listing_to_available(
            listing_id, listing_version
        )
    except grpc.aio.AioRpcError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Inventory rollback failed: {exc.details()}",
        )

    # 4. Mark claim as CANCELLED in Claim Log
    async with httpx.AsyncClient() as client:
        patch_resp = await client.patch(
            f"{CLAIM_LOG_URL}/logs/{claim_id}",
            json={"status": "CANCELLED"},
            timeout=10.0,
        )
        patch_resp.raise_for_status()

    logger.info(
        "Claim %s cancelled by charity %s — listing %s rolled back to v%s",
        claim_id, body.charity_id, listing_id, available_version,
    )

    # 5. Promote next from waitlist (auto-assigns listing to next eligible charity)
    #    available_version is passed so the promotion lock uses the correct version.
    promoted_charity_id, _ = await try_promote_next(
        listing_id=listing_id,
        available_version=available_version,
        claim_log_url=CLAIM_LOG_URL,
    )

    if not promoted_charity_id:
        # Waitlist empty — item is freely claimable again; notify auditor
        await publisher.publish_claim_cancelled(
            claim_id=claim_id,
            listing_id=listing_id,
            charity_id=body.charity_id,
        )
