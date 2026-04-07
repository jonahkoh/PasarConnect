"""
Claim Service — Orchestrator.

This service is intentionally stateless: no local DB and no ORM models.
It coordinates the workflow across Verification (gRPC), Inventory (gRPC),
Claim Log (gRPC), and RabbitMQ.
"""
import logging
import os
from contextlib import asynccontextmanager

from datetime import datetime, timezone, timedelta
from typing import Annotated

import grpc
import httpx
import asyncio
import claim_log_pb2
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException

import claim_log_client
import inventory_client
import publisher
import waitlist_grpc_client
import waitlist_router
from schemas import ClaimCreate, ClaimResponse, CancelClaimRequest
from waitlist_router import try_promote_next, _is_window_active, has_active_queue, queue_resolution_loop, offer_timeout_loop, _pending_resolution
from shared.jwt_auth import verify_jwt_token
from verification_client import CharityNotEligibleError, cancel_claim_quota, record_noshow, record_late_cancel_warning, verify_charity  #need to separate verification logic into a new service!

load_dotenv()

logger = logging.getLogger(__name__)

CANCEL_WINDOW_MINUTES = int(os.getenv("CANCEL_WINDOW_MINUTES", "15"))
CANCEL_WINDOW = timedelta(minutes=CANCEL_WINDOW_MINUTES)

# Internal HTTP base URL for the Claim Log service (not exposed through Kong).
CLAIM_LOG_HTTP = os.getenv("CLAIM_LOG_HTTP_URL", "http://claim-log-service:8006")
WAITLIST_HTTP  = os.getenv("WAITLIST_SERVICE_URL", "http://waitlist-service:8010")


def _within_cancel_window(created_at_str: str) -> bool:
    """Returns True if the claim was created within CANCEL_WINDOW of now."""
    if not created_at_str:
        return True  # err on side of restoring quota if timestamp unavailable
    try:
        dt = datetime.fromisoformat(created_at_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt) <= CANCEL_WINDOW
    except (ValueError, TypeError):
        return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Hydrate the resolution set with any QUEUING entries that survived a restart.
    # Delay 5s to let inventory gRPC become ready before we attempt connections.
    await asyncio.sleep(5)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{WAITLIST_HTTP}/waitlist/queuing-listings")
        if resp.status_code == 200:
            for listing_id in resp.json().get("listing_ids", []):
                # Check window still active so we don't re-schedule already-expired ones
                is_active, _, window_closes_at = await _is_window_active(listing_id)
                if is_active and window_closes_at:
                    from datetime import datetime, timezone
                    closes_dt = datetime.fromisoformat(window_closes_at)
                    if closes_dt.tzinfo is None:
                        closes_dt = closes_dt.replace(tzinfo=timezone.utc)
                    _pending_resolution[listing_id] = closes_dt
                elif not is_active:
                    # Window already expired — resolve immediately in background
                    from waitlist_router import _resolve_queue_window
                    asyncio.create_task(_resolve_queue_window(listing_id))
    except Exception as exc:
        logger.warning("Startup hydration of pending queue resolutions failed (non-fatal): %s", exc)

    task = asyncio.create_task(queue_resolution_loop())
    task2 = asyncio.create_task(offer_timeout_loop())
    yield
    task.cancel()
    task2.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    try:
        await task2
    except asyncio.CancelledError:
        pass


app = FastAPI(title="PasarConnect — Claim Service", lifespan=lifespan)
app.include_router(waitlist_router.router)


# -- Routes --------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "claim"}


@app.get("/claims/mine")
async def get_my_claims(token_payload: Annotated[dict, Depends(verify_jwt_token)]):
    """Return all claims for the authenticated charity user, ordered newest first."""
    charity_id = int(token_payload["sub"])
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{CLAIM_LOG_HTTP}/logs/{charity_id}")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Claim log unavailable")
    return resp.json()


@app.get("/claims/listing/{listing_id}/active")
async def get_active_claim_for_listing(listing_id: int):
    """Return the current PENDING_COLLECTION / AWAITING_VENDOR_APPROVAL claim for a listing."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{CLAIM_LOG_HTTP}/logs/listing/{listing_id}/active")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="No active claim for this listing")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Claim log unavailable")
    return resp.json()


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
async def create_claim(body: ClaimCreate, token_payload: Annotated[dict, Depends(verify_jwt_token)]):
    jwt_charity_id = int(token_payload["sub"])
    if jwt_charity_id != body.charity_id:
        raise HTTPException(status_code=403, detail="Token charity_id mismatch")

    # 0) Block direct claims while the queue window is active for this listing.
    window_active, _listed_at, window_closes_at = await _is_window_active(body.listing_id)
    if window_active:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "queue_window_active",
                "message": "This listing is in its charity queue window. Join the waitlist to be considered.",
                "window_closes_at": window_closes_at,
                "join_url": f"/claims/{body.listing_id}/waitlist",
            },
        )

    # 0b) Block direct claims when an active queue already exists for this listing.
    if await has_active_queue(body.listing_id):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "queue_exists",
                "message": "This listing has an active waitlist queue. Please join the queue.",
                "join_url": f"/claims/{body.listing_id}/waitlist",
            },
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
        # VerifyCharity already consumed a quota slot above — restore it now that the
        # claim cannot proceed, so the charity is not penalised for a race condition.
        await cancel_claim_quota(charity_id=body.charity_id, listing_id=body.listing_id)
        if code == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Listing not found")
        if code == grpc.StatusCode.ABORTED:
            raise HTTPException(status_code=409, detail="Listing already claimed -- please refresh")
        raise HTTPException(status_code=503, detail="Inventory service unavailable")

    # 3) Persist to Claim Log service. If this fails, rollback inventory lock.
    try:
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

        # Restore quota slot — inventory was rolled back so the charity should be
        # free to retry without the slot being silently consumed.
        await cancel_claim_quota(charity_id=body.charity_id, listing_id=body.listing_id)

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


@app.delete("/claims/{claim_id}", status_code=200)
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

    # 4b. Restore daily quota only if within the cancellation grace window.
    # After CANCEL_WINDOW_MINUTES the slot is consumed — penalises late voluntary cancels.
    is_late_cancel = not _within_cancel_window(getattr(claim, "created_at", ""))
    if not is_late_cancel:
        await cancel_claim_quota(charity_id=body.charity_id, listing_id=listing_id)
    else:
        logger.warning(
            "Late cancellation outside %d-min window for claim %s charity %s — quota not restored",
            CANCEL_WINDOW_MINUTES, claim_id, body.charity_id,
        )
        # Record in Verification Service so standing/warning_count is updated.
        await record_late_cancel_warning(charity_id=body.charity_id, claim_id=claim_id)

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

    return {"status": "cancelled", "late_cancel_warning": is_late_cancel}


@app.post("/claims/{claim_id}/noshow", status_code=200)
async def noshow_claim(claim_id: int):
    """
    Called by the vendor when a charity fails to collect their claim.

    Flow:
      1. Fetch claim from Claim Log — validates it exists.
      2. Validate: claim must be PENDING_COLLECTION or AWAITING_VENDOR_APPROVAL.
      3. Mark claim CANCELLED in Claim Log.
      4. Rollback Inventory → AVAILABLE.
      5. Record no-show in Verification Service (updates charity standing/ban).
      6. Publish claim.cancelled event.
    """
    # 1. Fetch claim record
    try:
        claim = await claim_log_client.get_claim_log(claim_id)
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)

    # 2. Validate status
    if claim.status not in (claim_log_pb2.PENDING_COLLECTION, claim_log_pb2.AWAITING_VENDOR_APPROVAL):
        raise HTTPException(
            status_code=409,
            detail="No-show can only be recorded for PENDING_COLLECTION or AWAITING_VENDOR_APPROVAL claims",
        )

    # 3. Mark claim CANCELLED in Claim Log
    try:
        await claim_log_client.update_claim_status(claim_id, claim_log_pb2.CANCELLED)
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)

    # 4. Rollback Inventory → AVAILABLE
    available_version = None
    try:
        available_version = await inventory_client.rollback_listing_to_available(
            claim.listing_id, claim.listing_version
        )
    except grpc.aio.AioRpcError:
        logger.error("Inventory rollback failed for noshow claim_id=%s", claim_id)
        # Don't block — no-show must still be recorded

    # 5. Record no-show in Verification Service (raises 503 if unavailable)
    await record_noshow(charity_id=claim.charity_id, claim_id=claim_id)

    # 6. Promote next waitlist charity if inventory was successfully rolled back
    if available_version is not None:
        promoted_charity_id, _ = await try_promote_next(
            listing_id=claim.listing_id,
            available_version=available_version,
        )
        if not promoted_charity_id:
            await publisher.publish_claim_cancelled(
                claim_id=claim_id,
                listing_id=claim.listing_id,
                charity_id=claim.charity_id,
            )

    return {
        "status": "ok",
        "claim_id": claim_id,
        "charity_id": claim.charity_id,
        "noshow_recorded": True,
    }


@app.post("/claims/{claim_id}/arrive")
async def arrive_claim(claim_id: int):
    try:
        claim = await claim_log_client.get_claim_log(claim_id)
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)

    try:
        await claim_log_client.update_claim_status(
            claim_id=claim_id,
            new_status=claim_log_pb2.AWAITING_VENDOR_APPROVAL,
        )
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)

    # Notify vendor that charity is physically on-site.
    await publisher.publish_claim_arrived(
        claim_id=claim_id,
        listing_id=claim.listing_id,
        charity_id=claim.charity_id,
    )

    return {
        "status": "ok",
        "claim_id": claim_id,
        "new_status": "AWAITING_VENDOR_APPROVAL",
    }


@app.post("/claims/{claim_id}/approve")
async def approve_claim(claim_id: int):
    # Fetch claim first to get charity_id (needed for waitlist update)
    try:
        claim_record = await claim_log_client.get_claim_log(claim_id)
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)
    charity_id = claim_record.charity_id
    listing_id_for_waitlist = claim_record.listing_id

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

    # Mark the collecting charity's waitlist entry as COLLECTED (best-effort)
    await waitlist_grpc_client.update_charity_entry(listing_id_for_waitlist, charity_id, "COLLECTED")

    # Cancel any remaining WAITING/QUEUING entries — listing is now SOLD
    await waitlist_grpc_client.cancel_all_active_entries(listing_id_for_waitlist)

    # Notify queue members that the item is gone
    await publisher.publish_waitlist_cancelled(listing_id_for_waitlist)

    # Notify the collecting charity that their claim is complete
    await publisher.publish_claim_completed(
        claim_id=result.claim_id,
        listing_id=result.listing_id,
        charity_id=charity_id,
    )

    return {
        "status": "ok",
        "claim_id": result.claim_id,
        "new_status": "COMPLETED",
        "inventory_version": new_version,
    }


@app.post("/claims/{claim_id}/reject")
async def reject_claim(claim_id: int):
    # Fetch first to get charity_id — needed for quota restoration.
    try:
        claim = await claim_log_client.get_claim_log(claim_id)
    except grpc.aio.AioRpcError as exc:
        raise claim_log_client.map_claim_log_grpc_error(exc)

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

    # Restore quota — vendor rejected, not charity's fault (best-effort)
    await cancel_claim_quota(charity_id=claim.charity_id, listing_id=result.listing_id)

    # Promote next waitlist charity or publish item-available event
    promoted_charity_id, _ = await try_promote_next(
        listing_id=result.listing_id,
        available_version=new_version,
    )
    if not promoted_charity_id:
        await publisher.publish_claim_cancelled(
            claim_id=claim_id,
            listing_id=result.listing_id,
            charity_id=claim.charity_id,
        )

    return {
        "status": "ok",
        "claim_id": result.claim_id,
        "new_status": "CANCELLED",
        "inventory_version": new_version,
    }
