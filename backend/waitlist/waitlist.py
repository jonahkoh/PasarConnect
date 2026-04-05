"""
Waitlist Service — atomic microservice owning the charity queue for listings.

Endpoints:
  GET    /health                                     — liveness probe
  POST   /waitlist/{listing_id}/entries              — charity joins the queue
  GET    /waitlist/{listing_id}/entries              — view queue (?status=WAITING)
  DELETE /waitlist/{listing_id}/entries/{charity_id} — charity leaves voluntarily
  PATCH  /waitlist/entries/{entry_id}               — internal: mark PROMOTED or CANCELLED

External callers  : Charity Dashboard (join / view / leave via Claim Service proxy).
Internal callers  : Claim Service try_promote_next (PATCH status).
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import select, nullslast
from sqlalchemy.exc import IntegrityError

from database import AsyncSessionLocal, init_db
from grpc_server import start_grpc_server
from models import WaitlistEntry, WaitlistEntryStatus
from schemas import (
    WaitlistEntryOut,
    WaitlistJoin,
    WaitlistPosition,
    WaitlistResolve,
    WaitlistStatusUpdate,
)

load_dotenv()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    grpc_server = await start_grpc_server()
    yield
    await grpc_server.stop(grace=5)


app = FastAPI(title="PasarConnect — Waitlist Service", lifespan=lifespan)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "waitlist"}


# ── Charity-facing endpoints ───────────────────────────────────────────────────

@app.post("/waitlist/{listing_id}/entries", response_model=WaitlistPosition, status_code=201)
async def join_waitlist(listing_id: int, body: WaitlistJoin):
    """Charity joins the queue for a listing. Returns their FIFO position (1 = next)."""
    async with AsyncSessionLocal() as db:
        count_result = await db.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.listing_id == listing_id,
                WaitlistEntry.status == WaitlistEntryStatus.WAITING,
            )
        )
        current_queue = count_result.scalars().all()

        entry = WaitlistEntry(
            listing_id=listing_id,
            charity_id=body.charity_id,
            status=body.status,
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


@app.get("/waitlist/{listing_id}/entries", response_model=list[WaitlistEntryOut])
async def get_waitlist(
    listing_id: int,
    status: Optional[str] = Query(default="WAITING"),
):
    """
    Returns entries for a listing ordered by joined_at (FIFO).
    Use ?status=WAITING (default) to see only queued charities.
    Omit the query param (or pass status=) to get all statuses.
    """
    async with AsyncSessionLocal() as db:
        query = select(WaitlistEntry).where(WaitlistEntry.listing_id == listing_id)
        if status:
            query = query.where(WaitlistEntry.status == status)
        query = query.order_by(
            nullslast(WaitlistEntry.rank),
            WaitlistEntry.joined_at.asc(),
        )
        result = await db.execute(query)
        entries = result.scalars().all()

    return [
        WaitlistEntryOut(
            id=e.id,
            listing_id=e.listing_id,
            charity_id=e.charity_id,
            joined_at=e.joined_at,
            status=e.status,
            position=i + 1,
        )
        for i, e in enumerate(entries)
    ]


@app.delete("/waitlist/{listing_id}/entries/{charity_id}", status_code=204)
async def leave_waitlist(listing_id: int, charity_id: int):
    """Charity voluntarily removes themselves from the queue."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.listing_id == listing_id,
                WaitlistEntry.charity_id == charity_id,
                WaitlistEntry.status.in_([
                    WaitlistEntryStatus.WAITING, WaitlistEntryStatus.QUEUING
                ]),
            )
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Not found on waitlist for this listing")

        entry.status = WaitlistEntryStatus.CANCELLED
        await db.commit()
        logger.info("Charity %s left waitlist for listing %s", charity_id, listing_id)


@app.delete("/waitlist/{listing_id}/entries", status_code=200)
async def cancel_all_active_entries(listing_id: int):
    """
    Cancel all WAITING and QUEUING entries for a listing.
    Called by the Claim Service when a listing is SOLD (approved) so no
    dangling queue entries remain after the food has been collected.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.listing_id == listing_id,
                WaitlistEntry.status.in_([
                    WaitlistEntryStatus.WAITING, WaitlistEntryStatus.QUEUING
                ]),
            )
        )
        entries = result.scalars().all()
        count = len(entries)
        for entry in entries:
            entry.status = WaitlistEntryStatus.CANCELLED
        await db.commit()

    logger.info("Cancelled %s active waitlist entries for listing %s (listing sold)", count, listing_id)
    return {"listing_id": listing_id, "cancelled_count": count}


# ── Internal endpoint (called by Claim Service try_promote_next) ──────────────

@app.patch("/waitlist/entries/{entry_id}", status_code=200)
async def update_entry_status(entry_id: int, body: WaitlistStatusUpdate):
    """
    Mark a waitlist entry as PROMOTED or CANCELLED.
    Called exclusively by the Claim Service during promotion orchestration.
    """
    allowed = {
        WaitlistEntryStatus.OFFERED,
        WaitlistEntryStatus.CANCELLED,
        WaitlistEntryStatus.COLLECTED,
    }
    if body.status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of {allowed}")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Waitlist entry not found")

        entry.status = body.status
        await db.commit()
        logger.info("Entry %s marked %s", entry_id, body.status)
        return {"id": entry_id, "status": body.status}


# ── Queue window resolution (called by Claim Service) ───────────────────────

@app.post("/waitlist/{listing_id}/resolve", status_code=200)
async def resolve_queue(listing_id: int, body: WaitlistResolve):
    """
    Bulk-set rank/score/resolved_at on QUEUING entries and flip their status to WAITING.
    Called by the Claim Service after the queue window closes.
    Idempotent: entries already WAITING are updated with new rank/score but status is unchanged.
    """
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        for item in body.entries:
            result = await db.execute(
                select(WaitlistEntry).where(
                    WaitlistEntry.id == item.entry_id,
                    WaitlistEntry.listing_id == listing_id,
                )
            )
            entry = result.scalar_one_or_none()
            if entry is None:
                continue
            entry.rank = item.rank
            entry.score = item.score
            entry.resolved_at = now
            if entry.status == WaitlistEntryStatus.QUEUING:
                entry.status = WaitlistEntryStatus.WAITING
        await db.commit()

    logger.info(
        "Queue resolved for listing %s: %s entries ranked",
        listing_id, len(body.entries),
    )
    return {"listing_id": listing_id, "resolved_count": len(body.entries)}
