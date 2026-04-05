"""
Waitlist proxy endpoints for the Claim Service.

All persistent state is owned by the Waitlist Service (port 8010).
The Claim Service communicates with it exclusively via gRPC (port 50053).

POST   /claims/{listing_id}/waitlist              — charity joins the queue
GET    /claims/{listing_id}/waitlist              — view current queue (position-ordered)
DELETE /claims/{listing_id}/waitlist/{charity_id} — charity leaves voluntarily
POST   /claims/{listing_id}/waitlist/accept       — charity accepts a slot OFFER
POST   /claims/{listing_id}/waitlist/decline      — charity declines a slot OFFER

Status lifecycle:
  QUEUING  → registered during the 2-min queue window (pre-ranking)
  WAITING  → in queue post-window; awaiting their turn (ranked or FIFO)
  OFFERED  → rank-1 charity notified; awaiting accept/decline
  CANCELLED→ left voluntarily, declined, no-show, or listing sold
  COLLECTED→ charity accepted and successfully collected the item

Internal helper (called by claim.py endpoints):
  try_promote_next(listing_id, available_version)
    → marks the best eligible WAITING charity as OFFERED (gRPC) + notifies
    → returns (offered_charity_id, new_version) or (None, available_version)

  has_active_queue(listing_id) → bool
    → True if any WAITING / QUEUING / OFFERED entries exist (direct claims blocked)
"""
import logging
import os
from datetime import datetime, timezone, timedelta

import grpc
import claim_log_pb2
from fastapi import APIRouter, HTTPException

import claim_log_client
import inventory_client
import publisher
import verification_client
import waitlist_grpc_client
from schemas import ClaimResponse, WaitlistJoin, WaitlistPosition, WaitlistListEntry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/claims", tags=["waitlist"])

QUEUE_WINDOW_MINUTES = float(os.getenv("QUEUE_WINDOW_MINUTES", "5"))
QUEUE_WINDOW = timedelta(minutes=QUEUE_WINDOW_MINUTES)

# Statuses visible to charity-facing GET /waitlist
_VISIBLE_STATUSES = {"QUEUING", "WAITING", "OFFERED"}

# Statuses that block a direct claim — if any exist, the listing has an active queue
_BLOCKING_STATUSES = {"QUEUING", "WAITING", "OFFERED"}


# ── Window helpers ────────────────────────────────────────────────────────

async def _is_window_active(listing_id: int) -> tuple[bool, str, str]:
    """
    Calls GetListing RPC to get listed_at, then checks if we’re still inside the queue window.
    Returns (is_active, listed_at_iso, window_closes_at_iso).
    Fail-open: returns (False, "", "") on any error so direct claims are never blocked.
    """
    try:
        listing = await inventory_client.get_listing(listing_id)
        listed_at_str = listing.listed_at
        if not listed_at_str:
            return False, "", ""
        listed_at = datetime.fromisoformat(listed_at_str)
        if listed_at.tzinfo is None:
            listed_at = listed_at.replace(tzinfo=timezone.utc)
        window_closes_at = listed_at + QUEUE_WINDOW
        is_active = datetime.now(timezone.utc) < window_closes_at
        return is_active, listed_at_str, window_closes_at.isoformat()
    except Exception as exc:
        logger.warning(
            "_is_window_active failed for listing %s (fail-open → False): %s", listing_id, exc
        )
        return False, "", ""


async def _resolve_queue_window(listing_id: int) -> None:
    """
    Lazy resolution: scores and ranks all QUEUING entries for a listing, persists
    rank/score via the Waitlist Service resolve endpoint, then promotes the best
    eligible charity via try_promote_next.

    No-op if there are no QUEUING entries (idempotent).
    """
    try:
        queuing = await waitlist_grpc_client.get_queuing_entries(listing_id)
    except HTTPException as exc:
        logger.error(
            "_resolve_queue_window: could not fetch QUEUING entries for listing %s: %s",
            listing_id, exc.detail,
        )
        return

    if not queuing:
        logger.info(
            "_resolve_queue_window: no QUEUING entries for listing %s — skipping", listing_id
        )
        return

    # Score each charity — fail-open: returns 0 per charity on error
    scored: list[dict] = []
    for entry in queuing:
        score = await verification_client.get_charity_score(entry["charity_id"])
        scored.append({
            "entry_id":   entry["id"],
            "charity_id": entry["charity_id"],
            "joined_at":  entry["joined_at"],
            "score":      score,
        })

    # Sort: score DESC → joined_at ASC → charity_id ASC (stable tiebreaker)
    scored.sort(key=lambda e: (-e["score"], e["joined_at"], e["charity_id"]))

    ranked_entries = [
        {"entry_id": e["entry_id"], "rank": rank + 1, "score": e["score"]}
        for rank, e in enumerate(scored)
    ]

    # Persist ranks → Waitlist Service flips QUEUING → WAITING with rank/score set
    await waitlist_grpc_client.resolve_queue(listing_id, ranked_entries)

    # Get current listing version then promote the best eligible charity
    try:
        listing = await inventory_client.get_listing(listing_id)
        current_version = listing.version
    except Exception as exc:
        logger.error(
            "_resolve_queue_window: could not get listing version for %s: %s — aborting promotion",
            listing_id, exc,
        )
        return

    logger.info(
        "_resolve_queue_window: resolved %s charities for listing %s — running promotion",
        len(ranked_entries), listing_id,
    )
    await try_promote_next(listing_id, current_version)


@router.post("/{listing_id}/waitlist", response_model=WaitlistPosition, status_code=201)
async def join_waitlist(listing_id: int, body: WaitlistJoin):
    """
    Charity joins the queue for a listing.

    During queue window  → registered as QUEUING (scored+ranked at window close).
    After window + no active queue + AVAILABLE → 409 "claim directly".
    After window (any other case)           → 409 "queue window closed".
    The window is the only registration period; no new entrants are accepted after it.
    """
    is_active, _listed_at, window_closes_at = await _is_window_active(listing_id)

    if is_active:
        return await waitlist_grpc_client.join_waitlist(listing_id, body.charity_id, status="QUEUING")

    # Window closed — run lazy resolution if any QUEUING entries remain
    await _resolve_queue_window(listing_id)

    queue_exists = await has_active_queue(listing_id)

    if not queue_exists:
        try:
            listing = await inventory_client.get_listing(listing_id)
            if listing.status == "AVAILABLE":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "listing_available",
                        "message": "No queue for this listing. Claim it directly!",
                        "claim_url": "/claims",
                    },
                )
        except grpc.aio.AioRpcError as exc:
            logger.warning(
                "join_waitlist: could not check listing %s status (proceeding): %s",
                listing_id, exc,
            )

    # Queue window has closed — no new registrations accepted.
    raise HTTPException(
        status_code=409,
        detail={
            "error": "queue_window_closed",
            "message": "The queue window for this listing has closed. No new registrations are accepted.",
        },
    )


@router.get("/{listing_id}/waitlist", response_model=list[WaitlistListEntry])
async def get_waitlist(listing_id: int):
    """
    Returns all active queue entries (QUEUING + WAITING + OFFERED), ordered by position.
    QUEUING  = registered during the window (unranked).
    WAITING  = post-window, ranked and waiting their turn.
    OFFERED  = rank-1 charity notified; pending acceptance.
    """
    all_entries = await waitlist_grpc_client.get_entries(listing_id, status="")
    active = [e for e in all_entries if e["status"] in _VISIBLE_STATUSES]
    return [
        WaitlistListEntry(
            listing_id=e["listing_id"],
            charity_id=e["charity_id"],
            position=e["position"],
            status=e["status"],
        )
        for e in active
    ]


@router.delete("/{listing_id}/waitlist/{charity_id}", status_code=204)
async def leave_waitlist(listing_id: int, charity_id: int):
    """Charity voluntarily removes themselves from the queue."""
    await waitlist_grpc_client.leave_waitlist(listing_id, charity_id)


@router.post("/{listing_id}/waitlist/accept", response_model=ClaimResponse, status_code=201)
async def accept_waitlist_offer(listing_id: int, body: WaitlistJoin):
    """
    Charity accepts the OFFERED slot.

    The inventory is already locked (listing is PENDING_COLLECTION) from when the offer
    was made. This endpoint creates the formal claim log entry and returns the claim.
    Raises 404 if no active OFFERED entry exists for this charity.
    """
    charity_id = body.charity_id

    entry = await waitlist_grpc_client.get_entry(listing_id, charity_id)
    if not entry or entry["status"] != "OFFERED":
        raise HTTPException(
            status_code=404,
            detail="No active offer for this charity on this listing. "
                   "Check GET /claims/{listing_id}/waitlist for your current status.",
        )

    try:
        listing = await inventory_client.get_listing(listing_id)
        current_version = listing.version
    except grpc.aio.AioRpcError as exc:
        raise HTTPException(status_code=503, detail=f"Inventory service unavailable: {exc.details()}")

    try:
        claim_record = await claim_log_client.create_claim_log(
            listing_id=listing_id,
            charity_id=charity_id,
            listing_version=current_version,
            status=claim_log_pb2.PENDING_COLLECTION,
        )
    except grpc.aio.AioRpcError as exc:
        logger.error("Claim log failed for waitlist accept listing=%s charity=%s: %s",
                     listing_id, charity_id, exc)
        try:
            await inventory_client.rollback_listing_to_available(listing_id, current_version)
        except grpc.aio.AioRpcError:
            logger.error("Rollback failed after claim log failure for listing=%s", listing_id)
        raise HTTPException(status_code=503, detail="Claim could not be finalized. Please retry.")

    await publisher.publish_claim_success(
        claim_id=claim_record.id, listing_id=listing_id, charity_id=charity_id,
    )
    logger.info("Waitlist accept: charity %s accepted slot for listing %s (claim %s)",
                charity_id, listing_id, claim_record.id)

    return {
        "id": claim_record.id,
        "listing_id": claim_record.listing_id,
        "charity_id": claim_record.charity_id,
        "listing_version": claim_record.listing_version,
        "status": claim_log_pb2.ClaimStatus.Name(claim_record.status),
        "created_at": getattr(claim_record, "created_at", datetime.now(timezone.utc)),
        "updated_at": getattr(claim_record, "updated_at", None),
    }


@router.post("/{listing_id}/waitlist/decline", status_code=200)
async def decline_waitlist_offer(listing_id: int, body: WaitlistJoin):
    """
    Charity declines the OFFERED slot.

    Rolls back the inventory lock and offers the slot to the next eligible charity.
    Raises 404 if no active OFFERED entry exists for this charity.
    """
    charity_id = body.charity_id

    entry = await waitlist_grpc_client.get_entry(listing_id, charity_id)
    if not entry or entry["status"] != "OFFERED":
        raise HTTPException(
            status_code=404,
            detail="No active offer for this charity on this listing.",
        )

    await waitlist_grpc_client.update_entry_status(entry["id"], "CANCELLED")

    try:
        listing = await inventory_client.get_listing(listing_id)
        available_version = await inventory_client.rollback_listing_to_available(
            listing_id, listing.version
        )
    except grpc.aio.AioRpcError as exc:
        logger.error("Inventory rollback failed after decline listing=%s charity=%s: %s",
                     listing_id, charity_id, exc)
        raise HTTPException(status_code=503, detail="Inventory rollback failed. Please contact support.")

    logger.info("Waitlist decline: charity %s declined — trying next in queue for listing %s",
                charity_id, listing_id)

    offered_charity_id, _ = await try_promote_next(listing_id, available_version)
    if not offered_charity_id:
        await publisher.publish_claim_cancelled(
            claim_id=0, listing_id=listing_id, charity_id=charity_id
        )

    return {"status": "declined", "listing_id": listing_id, "charity_id": charity_id}


# ── Queue check helper (used by create_claim in claim.py) ─────────────────────

async def has_active_queue(listing_id: int) -> bool:
    """
    Returns True if any QUEUING / WAITING / OFFERED entries exist for this listing.
    Fail-open: returns False on error so create_claim is never blocked by a service hiccup.
    """
    try:
        all_entries = await waitlist_grpc_client.get_entries(listing_id, status="")
        return any(e["status"] in _BLOCKING_STATUSES for e in all_entries)
    except Exception as exc:
        logger.warning(
            "has_active_queue failed for listing %s (fail-open → False): %s", listing_id, exc
        )
        return False


# ── Internal orchestration helper ─────────────────────────────────────────────

async def try_promote_next(
    listing_id: int,
    available_version: int,
) -> tuple[int | None, int]:
    """
    Walk through the WAITING queue (ordered by rank ASC, then joined_at ASC).
    For each charity:
      1. VerifyCharity (quota + legal check via Verification Service gRPC).
      2. If eligible: lock inventory (available_version → new_version),
         mark waitlist entry OFFERED, publish claim.waitlist.offered.
         STOP — the charity must now call POST /waitlist/accept or /decline.
      3. If ineligible: mark entry CANCELLED, try the next charity.
    Returns (offered_charity_id, new_version).
    Returns (None, available_version) if the queue is exhausted.
    """
    try:
        entries = await waitlist_grpc_client.get_waiting_entries(listing_id)
    except HTTPException as exc:
        logger.error("Could not fetch waitlist entries during promotion: %s", exc.detail)
        return None, available_version

    current_version = available_version

    for entry in entries:
        charity_id = entry["charity_id"]
        entry_id   = entry["id"]

        # 1. Eligibility check via Verification Service
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
            await waitlist_grpc_client.update_entry_status(entry_id, "CANCELLED")
            continue

        # 2. Lock inventory for this charity (current_version → new_version)
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
            return None, current_version

        # 3. Mark entry OFFERED — charity must accept/decline via the API
        await waitlist_grpc_client.update_entry_status(entry_id, "OFFERED")

        # 4. Notify charity — they'll see a pop-up to accept or decline
        await publisher.publish_waitlist_offered(
            listing_id=listing_id,
            charity_id=charity_id,
        )

        logger.info(
            "Waitlist: offered listing %s to charity %s (v%s → v%s)",
            listing_id, charity_id, available_version, new_version,
        )
        return charity_id, new_version

    # Queue exhausted — no eligible charity found
    logger.info("Waitlist exhausted for listing %s — item is now publicly available", listing_id)
    return None, available_version
