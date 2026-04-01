"""
Claim Service — Orchestrator.

This service is intentionally stateless: no local DB and no ORM models.
It coordinates the workflow across Verification (gRPC), Inventory (gRPC),
Claim Log (gRPC), and RabbitMQ.
"""
import logging
import os
from contextlib import asynccontextmanager

from datetime import datetime, timezone
from typing import Annotated

import grpc
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException

import claim_log_client
import inventory_client
import publisher
import waitlist_router
from schemas import ClaimCreate, ClaimResponse, CancelClaimRequest
from waitlist_db import init_db
from waitlist_router import try_promote_next
from shared.jwt_auth import verify_jwt_token
from verification_client import CharityNotEligibleError, verify_charity  #need to separate verification logic into a new service!

load_dotenv()

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()   # create waitlist_entries table if it doesn't exist
    yield


app = FastAPI(title="PasarConnect — Claim Service", lifespan=lifespan)
app.include_router(waitlist_router.router)


# -- Routes --------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "claim"}


async def _verify_claim_eligibility(charity_id: int, listing_id: int) -> None:
    """
    Calls Verification Service via gRPC -> OutSystems REST.
    Raises HTTP 403 if charity is ineligible (e.g. MISSING_WAIVER).
    Raises HTTP 503 if Verification Service is unreachable.
    """
    try:
        await verify_charity(charity_id=charity_id, listing_id=listing_id)
    except CharityNotEligibleError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "charity_not_eligible",
                "reason": exc.reason,
            },
        )


@app.post("/claims", response_model=ClaimResponse, status_code=201)
async def create_claim(
    body: ClaimCreate,
    token_payload: Annotated[dict, Depends(verify_jwt_token)],
):
    # Security: derive charity_id from the verified JWT sub claim, not from
    # the request body. Prevents a charity from claiming on behalf of another.
    jwt_charity_id = int(token_payload["sub"])
    if jwt_charity_id != body.charity_id:
        raise HTTPException(
            status_code=403,
            detail="charity_id in request does not match authenticated identity",
        )

    # 1) Verify eligibility via Verification Service -> OutSystems.
    await _verify_claim_eligibility(body.charity_id, body.listing_id)

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
            raise HTTPException(status_code=409, detail="Listing already claimed -- please refresh")
        raise HTTPException(status_code=503, detail="Inventory service unavailable")

    # 3) Persist to Claim Log service. If this fails, rollback inventory lock.
    try:
        import claim_log_pb2

        claim_record = await claim_log_client.create_claim_log(
            listing_id=body.listing_id,
            charity_id=body.charity_id,
            listing_version=new_version,
            status=claim_log_pb2.PENDING_COLLECTION,
        )
    except grpc.aio.AioRpcError as exc:
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
        claim_id=claim_record.id,
        listing_id=claim_record.listing_id,
        charity_id=claim_record.charity_id,
    )

    return {
        "id": claim_record.id,
        "listing_id": claim_record.listing_id,
        "charity_id": claim_record.charity_id,
        "listing_version": claim_record.listing_version,
        "status": claim_log_pb2.ClaimStatus.Name(claim_record.status),
        "created_at": getattr(claim_record, "created_at", datetime.now(timezone.utc)),
        "updated_at": getattr(claim_record, "updated_at", None),
    }


@app.delete("/claims/{claim_id}", status_code=204)
async def cancel_claim(claim_id: int, body: CancelClaimRequest):
    """
    Cancel an active PENDING_COLLECTION claim.

    Flow:
      1. Fetch claim from Claim Log via gRPC — get listing_id, charity_id, listing_version.
      2. Validate: caller must be the claim owner; status must be PENDING_COLLECTION.
      3. Rollback Inventory: PENDING_COLLECTION → AVAILABLE  (returns v_available).
      4. Mark claim CANCELLED in Claim Log via gRPC.
      5. Walk waitlist in FIFO order:
           a. Verify next charity (quota + legal check via Verification Service).
           b. If eligible: lock Inventory AVAILABLE → PENDING_COLLECTION,
              create a new claim log entry, mark waitlist entry PROMOTED,
              publish claim.waitlist.promoted → Notification Service WebSockets the charity.
           c. If ineligible: mark CANCELLED, try next charity.
           d. If queue is exhausted: publish claim.cancelled (item is freely claimable again).
    """
    import claim_log_pb2

    # 1. Fetch claim record via gRPC
    try:
        claim = await claim_log_client.get_claim_log(claim_id)
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)

    # 2. Validate ownership and status
    if claim.charity_id != body.charity_id:
        raise HTTPException(status_code=403, detail="Cannot cancel another charity's claim")
    if claim.status != claim_log_pb2.PENDING_COLLECTION:
        raise HTTPException(
            status_code=409,
            detail="Cannot cancel a claim that is not PENDING_COLLECTION",
        )

    listing_id      = claim.listing_id
    listing_version = claim.listing_version

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

    # 4. Mark claim as CANCELLED in Claim Log via gRPC
    try:
        await claim_log_client.update_claim_status(claim_id, claim_log_pb2.CANCELLED)
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)

    logger.info(
        "Claim %s cancelled by charity %s — listing %s rolled back to v%s",
        claim_id, body.charity_id, listing_id, available_version,
    )

    # 5. Promote next from waitlist (auto-assigns listing to next eligible charity)
    promoted_charity_id, _ = await try_promote_next(
        listing_id=listing_id,
        available_version=available_version,
    )

    if not promoted_charity_id:
        # Waitlist empty — item is freely claimable again; notify auditor
        await publisher.publish_claim_cancelled(
            claim_id=claim_id,
            listing_id=listing_id,
            charity_id=body.charity_id,
        )


@app.post("/claims/{claim_id}/arrive")
async def arrive_claim(claim_id: int):
    import claim_log_pb2

    try:
        result = await claim_log_client.update_claim_status(
            claim_id=claim_id,
            new_status=claim_log_pb2.AWAITING_VENDOR_APPROVAL,
        )
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)

    return {
        "status": "ok",
        "claim_id": result.claim_id,
        "new_status": "AWAITING_VENDOR_APPROVAL",
    }


@app.post("/claims/{claim_id}/approve")
async def approve_claim(claim_id: int):
    import claim_log_pb2

    try:
        result = await claim_log_client.update_claim_status(
            claim_id=claim_id,
            new_status=claim_log_pb2.COMPLETED,
        )
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)

    try:
        new_version = await inventory_client.mark_listing_sold(
            listing_id=result.listing_id,
            expected_version=result.listing_version,
        )
    except grpc.aio.AioRpcError:
        raise HTTPException(status_code=503, detail="Inventory update failed after claim approval")

    return {
        "status": "ok",
        "claim_id": result.claim_id,
        "new_status": "COMPLETED",
        "inventory_version": new_version,
    }


@app.post("/claims/{claim_id}/reject")
async def reject_claim(claim_id: int):
    import claim_log_pb2

    try:
        result = await claim_log_client.update_claim_status(
            claim_id=claim_id,
            new_status=claim_log_pb2.CANCELLED,
        )
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)

    try:
        new_version = await inventory_client.rollback_listing_to_available(
            listing_id=result.listing_id,
            expected_version=result.listing_version,
        )
    except grpc.aio.AioRpcError:
        raise HTTPException(status_code=503, detail="Inventory rollback failed after claim rejection")

    return {
        "status": "ok",
        "claim_id": result.claim_id,
        "new_status": "CANCELLED",
        "inventory_version": new_version,
    }
