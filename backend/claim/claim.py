"""
Claim Service — Orchestrator.

This service is intentionally stateless: no local DB and no ORM models.
It coordinates the workflow across Verification (gRPC), Inventory (gRPC),
Claim Log (HTTP), and RabbitMQ.
"""
import logging
import os
from contextlib import asynccontextmanager

import grpc
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

import inventory_client
import publisher
from schemas import ClaimCreate, ClaimResponse

load_dotenv()

logger = logging.getLogger(__name__)

VERIFICATION_GRPC_HOST = os.getenv("VERIFICATION_GRPC_HOST", "localhost")
VERIFICATION_GRPC_PORT = os.getenv("VERIFICATION_GRPC_PORT", "50052")
VERIFICATION_GRPC_ADDR = f"{VERIFICATION_GRPC_HOST}:{VERIFICATION_GRPC_PORT}"

CLAIM_LOG_URL = os.getenv("CLAIM_LOG_URL", "http://localhost:8006")


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


async def _post(client: httpx.AsyncClient, url: str, body: dict) -> dict:
    response = await client.post(url, json=body, timeout=10.0)
    response.raise_for_status()
    return response.json()


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
