"""
Waitlist proxy endpoints for the Claim Service.

All persistent state is now owned by the Waitlist Service (waitlist-service:8010).
These endpoints are thin HTTP proxies; the promotion orchestration logic stays here.

POST   /claims/{listing_id}/waitlist              — charity joins the queue
GET    /claims/{listing_id}/waitlist              — view current queue (position-ordered)
DELETE /claims/{listing_id}/waitlist/{charity_id} — charity leaves voluntarily

Internal helper (called by claim.py endpoints):
  try_promote_next(listing_id, available_version)
    → orchestrates promotion of the next eligible charity from the waitlist
    → returns (promoted_charity_id, new_version) or (None, available_version)
"""
import logging

import grpc
import claim_log_pb2
from fastapi import APIRouter, HTTPException

import claim_log_client
import inventory_client
import publisher
import verification_client
import waitlist_client
from schemas import WaitlistJoin, WaitlistPosition, WaitlistListEntry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/claims", tags=["waitlist"])



# ── Charity-facing endpoints (proxied to Waitlist Service) ────────────────────

@router.post("/{listing_id}/waitlist", response_model=WaitlistPosition, status_code=201)
async def join_waitlist(listing_id: int, body: WaitlistJoin):
    """Charity joins the waitlist for a listing. Returns their queue position."""
    return await waitlist_client.join_waitlist(listing_id, body.charity_id)


@router.get("/{listing_id}/waitlist", response_model=list[WaitlistListEntry])
async def get_waitlist(listing_id: int):
    """Returns the current WAITING queue for a listing, ordered by join time."""
    entries = await waitlist_client.get_waiting_entries(listing_id)
    return [
        WaitlistListEntry(
            listing_id=e["listing_id"],
            charity_id=e["charity_id"],
            position=e["position"],
        )
        for e in entries
    ]


@router.delete("/{listing_id}/waitlist/{charity_id}", status_code=204)
async def leave_waitlist(listing_id: int, charity_id: int):
    """Charity voluntarily removes themselves from the waitlist."""
    await waitlist_client.leave_waitlist(listing_id, charity_id)


# ── Internal orchestration helper ─────────────────────────────────────────────

async def try_promote_next(
    listing_id: int,
    available_version: int,
) -> tuple[int | None, int]:
    """
    Walk through the WAITING queue in FIFO order.
    For each charity:
      1. VerifyCharity (quota + legal check via Verification Service gRPC).
      2. If eligible: lock inventory (available_version → new_version), create
         claim log, mark waitlist entry PROMOTED, publish claim.waitlist.promoted.
      3. If ineligible: mark entry CANCELLED, try the next charity.
    Returns (promoted_charity_id, new_version).
    Returns (None, available_version) if the queue is exhausted.
    """
    try:
        entries = await waitlist_client.get_waiting_entries(listing_id)
    except HTTPException as exc:
        logger.error("Could not fetch waitlist entries during promotion: %s", exc.detail)
        return None, available_version

    current_version = available_version

    for entry in entries:
        charity_id = entry["charity_id"]
        entry_id   = entry["id"]

        # 1. Eligibility check via Verification Service (records quota on success)
        try:
            valid, reason = await verification_client.verify_charity_eligibility(
                charity_id, listing_id
            )
        except Exception as exc:
            logger.warning(
                "Verification call failed for charity %s: %s — skipping", charity_id, exc
            )
            valid, reason = False, "VERIFICATION_ERROR"

        if not valid:
            logger.warning(
                "Skipping waitlist charity %s for listing %s: %s",
                charity_id, listing_id, reason,
            )
            await waitlist_client.update_entry_status(entry_id, "CANCELLED")
            continue

        # 2. Lock inventory for promoted charity (current_version → new_version)
        try:
            new_version = await inventory_client.lock_listing_pending_collection(
                listing_id=listing_id,
                expected_version=current_version,
            )
        except grpc.aio.AioRpcError as exc:
            logger.error(
                "Inventory lock failed during waitlist promotion for listing %s: [%s] %s",
                listing_id, exc.code(), exc.details(),
            )
            # Item may have been grabbed by someone else — abort promotion
            return None, current_version

        # 3. Create claim log entry for promoted charity via gRPC
        try:
            claim_record = await claim_log_client.create_claim_log(
                listing_id=listing_id,
                charity_id=charity_id,
                listing_version=new_version,
                status=claim_log_pb2.PENDING_COLLECTION,
            )
        except grpc.aio.AioRpcError as exc:
            logger.error(
                "Claim log failed for promoted charity %s listing %s: [%s] %s — rolling back",
                charity_id, listing_id, exc.code(), exc.details(),
            )
            try:
                await inventory_client.rollback_listing_to_available(listing_id, new_version)
            except grpc.aio.AioRpcError:
                logger.error(
                    "Rollback after claim log failure also failed for listing %s", listing_id
                )
            return None, available_version

        # 4. Mark waitlist entry as PROMOTED (best-effort — never aborts a successful promotion)
        await waitlist_client.update_entry_status(entry_id, "PROMOTED")

        # 5. Publish promotion event → Notification Service WebSockets the charity
        await publisher.publish_waitlist_promoted(
            claim_id=claim_record.id,
            listing_id=listing_id,
            charity_id=charity_id,
        )

        logger.info(
            "Waitlist: promoted charity %s to claim listing %s (v%s → v%s)",
            charity_id, listing_id, available_version, new_version,
        )
        return charity_id, new_version

    # Queue exhausted — no eligible charity found
    logger.info("Waitlist exhausted for listing %s — item is now publicly available", listing_id)
    return None, available_version
