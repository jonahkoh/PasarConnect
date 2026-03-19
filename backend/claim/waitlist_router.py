"""
Waitlist endpoints for the Claim Service.

POST   /claims/{listing_id}/waitlist              — charity joins the waitlist
GET    /claims/{listing_id}/waitlist              — view current queue (position-ordered)
DELETE /claims/{listing_id}/waitlist/{charity_id} — charity leaves voluntarily

Internal helper (used by cancel_claim in claim.py):
  try_promote_next(listing_id, available_version)
    → auto-assigns the item to the next eligible charity in line
    → returns (promoted_charity_id, new_inventory_version) or (None, available_version)
"""
import logging

import grpc
import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import inventory_client
import publisher
import verification_client
from schemas import WaitlistJoin, WaitlistPosition, WaitlistListEntry
from waitlist_db import AsyncSessionLocal, WaitlistEntry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/claims", tags=["waitlist"])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{listing_id}/waitlist", response_model=WaitlistPosition, status_code=201)
async def join_waitlist(listing_id: int, body: WaitlistJoin):
    """
    A charity joins the waitlist for a listing that is PENDING_COLLECTION.
    Returns their queue position (1 = next in line).
    """
    async with AsyncSessionLocal() as db:
        # Count how many charities are already WAITING ahead of this one
        count_result = await db.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.listing_id == listing_id,
                WaitlistEntry.status == "WAITING",
            )
        )
        current_queue = count_result.scalars().all()

        entry = WaitlistEntry(
            listing_id=listing_id,
            charity_id=body.charity_id,
            status="WAITING",
        )
        db.add(entry)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Already on the waitlist for this listing",
            )

        position = len(current_queue) + 1
        logger.info(
            "Charity %s joined waitlist for listing %s at position %s",
            body.charity_id, listing_id, position,
        )
        return WaitlistPosition(
            listing_id=listing_id,
            charity_id=body.charity_id,
            position=position,
        )


@router.get("/{listing_id}/waitlist", response_model=list[WaitlistListEntry])
async def get_waitlist(listing_id: int):
    """Returns the current WAITING queue for a listing, ordered by join time."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WaitlistEntry)
            .where(
                WaitlistEntry.listing_id == listing_id,
                WaitlistEntry.status == "WAITING",
            )
            .order_by(WaitlistEntry.joined_at)
        )
        entries = result.scalars().all()

    return [
        WaitlistListEntry(
            listing_id=e.listing_id,
            charity_id=e.charity_id,
            position=i + 1,
        )
        for i, e in enumerate(entries)
    ]


@router.delete("/{listing_id}/waitlist/{charity_id}", status_code=204)
async def leave_waitlist(listing_id: int, charity_id: int):
    """A charity voluntarily removes themselves from the waitlist."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.listing_id == listing_id,
                WaitlistEntry.charity_id == charity_id,
                WaitlistEntry.status == "WAITING",
            )
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Not found on waitlist for this listing")

        entry.status = "CANCELLED"
        await db.commit()
        logger.info("Charity %s left waitlist for listing %s", charity_id, listing_id)


# ── Internal helper ───────────────────────────────────────────────────────────

async def try_promote_next(
    listing_id: int,
    available_version: int,
    claim_log_url: str,
) -> tuple[int | None, int]:
    """
    Walk through the WAITING queue in FIFO order.
    For each charity:
      1. Run VerifyCharity (quota + legal check via gRPC).
      2. If eligible: lock inventory (available_version → new_version), create claim log,
         mark entry as PROMOTED, publish events, return (charity_id, new_version).
      3. If ineligible: mark entry as CANCELLED (skipped), try the next one.

    Returns (promoted_charity_id, final_version).
    If the queue is exhausted without a successful promotion, returns (None, available_version).
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WaitlistEntry)
            .where(
                WaitlistEntry.listing_id == listing_id,
                WaitlistEntry.status == "WAITING",
            )
            .order_by(WaitlistEntry.joined_at)
        )
        entries = result.scalars().all()

    current_version = available_version

    for entry in entries:
        charity_id = entry.charity_id

        # 1. Eligibility check via Verification Service (records quota on success)
        try:
            valid, reason = await verification_client.verify_charity_eligibility(
                charity_id, listing_id
            )
        except Exception as exc:
            logger.warning("Verification call failed for charity %s: %s — skipping", charity_id, exc)
            valid, reason = False, "VERIFICATION_ERROR"

        if not valid:
            logger.warning(
                "Skipping waitlist charity %s for listing %s: %s",
                charity_id, listing_id, reason,
            )
            async with AsyncSessionLocal() as db:
                r = await db.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry.id))
                e = r.scalar_one()
                e.status = "CANCELLED"
                await db.commit()
            continue

        # 2. Lock inventory for promoted charity (available_version → new_version)
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

        # 3. Create claim log entry for promoted charity
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{claim_log_url}/logs",
                    json={
                        "listing_id": listing_id,
                        "charity_id": charity_id,
                        "listing_version": new_version,
                        "status": "PENDING_COLLECTION",
                    },
                    timeout=10.0,
                )
                resp.raise_for_status()
                claim_record = resp.json()
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.error(
                "Claim log failed for promoted charity %s listing %s: %s — rolling back",
                charity_id, listing_id, exc,
            )
            # Roll back the inventory lock we just applied
            try:
                await inventory_client.rollback_listing_to_available(listing_id, new_version)
            except grpc.aio.AioRpcError:
                logger.error("Rollback after claim log failure also failed for listing %s", listing_id)
            return None, available_version

        # 4. Mark waitlist entry as PROMOTED
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry.id))
            e = r.scalar_one()
            e.status = "PROMOTED"
            await db.commit()

        # 5. Publish promotion event → Notification Service sends WebSocket to charity
        await publisher.publish_waitlist_promoted(
            claim_id=claim_record["id"],
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
