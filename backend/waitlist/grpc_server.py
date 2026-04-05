"""
Waitlist Service — gRPC server.

Implements WaitlistService as defined in proto/waitlist.proto.
Runs on port 50053 alongside the HTTP server (same process, same event loop).
All DB operations use the same AsyncSessionLocal as the REST layer.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import grpc

import waitlist_pb2
import waitlist_pb2_grpc
from database import AsyncSessionLocal
from models import WaitlistEntry, WaitlistEntryStatus
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy import nullslast

logger = logging.getLogger(__name__)

GRPC_PORT = int(os.getenv("WAITLIST_GRPC_PORT", "50053"))

# Statuses that count as "active" in the queue (not yet resolved)
_ACTIVE_STATUSES = {
    WaitlistEntryStatus.WAITING.value,
    WaitlistEntryStatus.QUEUING.value,
}

# Statuses that are allowed as targets for UpdateEntryStatus
_ALLOWED_UPDATE_STATUSES = {
    WaitlistEntryStatus.OFFERED.value,
    WaitlistEntryStatus.CANCELLED.value,
    WaitlistEntryStatus.COLLECTED.value,
}


def _entry_to_proto(entry: WaitlistEntry, position: int) -> waitlist_pb2.WaitlistEntryProto:
    joined = entry.joined_at
    if joined is None:
        joined_str = ""
    elif hasattr(joined, "isoformat"):
        if joined.tzinfo is None:
            joined = joined.replace(tzinfo=timezone.utc)
        joined_str = joined.isoformat()
    else:
        joined_str = str(joined)

    return waitlist_pb2.WaitlistEntryProto(
        id=entry.id,
        listing_id=entry.listing_id,
        charity_id=entry.charity_id,
        joined_at=joined_str,
        status=entry.status if isinstance(entry.status, str) else entry.status.value,
        position=position,
        rank=entry.rank or 0,
        score=entry.score or 0,
    )


class WaitlistServicer(waitlist_pb2_grpc.WaitlistServiceServicer):

    async def JoinWaitlist(self, request, context):
        listing_id = request.listing_id
        charity_id = request.charity_id
        status     = request.status or WaitlistEntryStatus.WAITING.value

        if listing_id <= 0 or charity_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "listing_id and charity_id must be > 0")
            return waitlist_pb2.PositionResponse()

        async with AsyncSessionLocal() as db:
            # Count current active entries to determine position
            count_result = await db.execute(
                select(WaitlistEntry).where(
                    WaitlistEntry.listing_id == listing_id,
                    WaitlistEntry.status == WaitlistEntryStatus.WAITING,
                )
            )
            current_queue = count_result.scalars().all()

            entry = WaitlistEntry(listing_id=listing_id, charity_id=charity_id, status=status)
            db.add(entry)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                await context.abort(grpc.StatusCode.ALREADY_EXISTS, "Already on the waitlist for this listing")
                return waitlist_pb2.PositionResponse()

        position = len(current_queue) + 1
        logger.info("Charity %s joined waitlist for listing %s at position %s (status=%s)",
                    charity_id, listing_id, position, status)
        return waitlist_pb2.PositionResponse(listing_id=listing_id, charity_id=charity_id, position=position)

    async def GetEntries(self, request, context):
        listing_id = request.listing_id
        status_filter = request.status  # "" = all

        async with AsyncSessionLocal() as db:
            query = select(WaitlistEntry).where(WaitlistEntry.listing_id == listing_id)
            if status_filter:
                query = query.where(WaitlistEntry.status == status_filter)
            query = query.order_by(nullslast(WaitlistEntry.rank), WaitlistEntry.joined_at.asc())
            result = await db.execute(query)
            entries = result.scalars().all()

        return waitlist_pb2.GetEntriesResponse(
            entries=[_entry_to_proto(e, i + 1) for i, e in enumerate(entries)]
        )

    async def GetEntry(self, request, context):
        listing_id = request.listing_id
        charity_id = request.charity_id

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WaitlistEntry).where(
                    WaitlistEntry.listing_id == listing_id,
                    WaitlistEntry.charity_id == charity_id,
                )
            )
            entry = result.scalar_one_or_none()

        if entry is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Waitlist entry not found")
            return waitlist_pb2.WaitlistEntryProto()

        return _entry_to_proto(entry, 1)

    async def LeaveWaitlist(self, request, context):
        listing_id = request.listing_id
        charity_id = request.charity_id

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
            if entry is None:
                await context.abort(grpc.StatusCode.NOT_FOUND, "Not found on waitlist for this listing")
                return waitlist_pb2.LeaveResponse()

            entry.status = WaitlistEntryStatus.CANCELLED
            await db.commit()

        logger.info("Charity %s left waitlist for listing %s", charity_id, listing_id)
        return waitlist_pb2.LeaveResponse(cancelled=True)

    async def UpdateEntryStatus(self, request, context):
        entry_id = request.entry_id
        new_status = request.status

        if new_status not in _ALLOWED_UPDATE_STATUSES:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"status must be one of {_ALLOWED_UPDATE_STATUSES}",
            )
            return waitlist_pb2.UpdateStatusResponse()

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WaitlistEntry).where(WaitlistEntry.id == entry_id)
            )
            entry = result.scalar_one_or_none()
            if entry is None:
                await context.abort(grpc.StatusCode.NOT_FOUND, "Waitlist entry not found")
                return waitlist_pb2.UpdateStatusResponse()

            entry.status = new_status
            await db.commit()

        logger.info("Entry %s status → %s", entry_id, new_status)
        return waitlist_pb2.UpdateStatusResponse(id=entry_id, status=new_status)

    async def UpdateCharityEntry(self, request, context):
        listing_id = request.listing_id
        charity_id = request.charity_id
        new_status = request.status

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WaitlistEntry).where(
                    WaitlistEntry.listing_id == listing_id,
                    WaitlistEntry.charity_id == charity_id,
                )
            )
            entry = result.scalar_one_or_none()
            if entry is None:
                # Best-effort: direct claims have no waitlist entry — silently succeed
                logger.info(
                    "UpdateCharityEntry: no entry for listing=%s charity=%s — no-op",
                    listing_id, charity_id,
                )
                return waitlist_pb2.UpdateStatusResponse(id=0, status=new_status)

            entry.status = new_status
            await db.commit()

        logger.info("Entry (listing=%s charity=%s) status → %s", listing_id, charity_id, new_status)
        return waitlist_pb2.UpdateStatusResponse(id=entry.id, status=new_status)

    async def CancelAllActive(self, request, context):
        listing_id = request.listing_id

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
            for e in entries:
                e.status = WaitlistEntryStatus.CANCELLED
            await db.commit()

        logger.info("CancelAllActive: cancelled %s entries for listing %s", count, listing_id)
        return waitlist_pb2.CancelAllResponse(listing_id=listing_id, cancelled_count=count)

    async def ResolveQueue(self, request, context):
        listing_id = request.listing_id
        # DB column is TIMESTAMP WITHOUT TIME ZONE — strip tzinfo before writing
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        async with AsyncSessionLocal() as db:
            for item in request.entries:
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

        ranked_count = len(request.entries)
        logger.info("ResolveQueue: %s entries ranked for listing %s", ranked_count, listing_id)
        return waitlist_pb2.ResolveQueueResponse(listing_id=listing_id, ranked_count=ranked_count)


async def start_grpc_server(host: str = "0.0.0.0", port: int = GRPC_PORT) -> grpc.aio.Server:
    server = grpc.aio.server()
    waitlist_pb2_grpc.add_WaitlistServiceServicer_to_server(WaitlistServicer(), server)
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    logger.info("Waitlist gRPC server listening on %s:%s", host, port)
    return server
