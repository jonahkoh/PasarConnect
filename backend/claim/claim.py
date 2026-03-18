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

import grpc
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

import inventory_client
import publisher
import claim_log_client
from schemas import ClaimCreate, ClaimResponse

load_dotenv()

logger = logging.getLogger(__name__)

VERIFICATION_GRPC_HOST = os.getenv("VERIFICATION_GRPC_HOST", "localhost")
VERIFICATION_GRPC_PORT = os.getenv("VERIFICATION_GRPC_PORT", "50052")
VERIFICATION_GRPC_ADDR = f"{VERIFICATION_GRPC_HOST}:{VERIFICATION_GRPC_PORT}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Stateless service: no startup DB work required.
    yield


app = FastAPI(title="PasarConnect — Claim Service", lifespan=lifespan)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "claim"}


async def _verify_claim_eligibility(charity_id: int, listing_id: int) -> None:
    """
    Verification gRPC call placeholder.

    Contract: raises HTTPException(403) when charity is not eligible.
    For now, the service is assumed to return VALID as requested.
    """
    # This hook keeps orchestration flow explicit and ready for the real proto.
    logger.info(
        "Verification assumed VALID for charity_id=%s listing_id=%s via %s",
        charity_id,
        listing_id,
        VERIFICATION_GRPC_ADDR,
    )


@app.post("/claims", response_model=ClaimResponse, status_code=201)
async def create_claim(body: ClaimCreate):
    # 1) Verify eligibility via Verification Service (assumed VALID).
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
            raise HTTPException(status_code=409, detail="Listing already claimed — please refresh")
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
