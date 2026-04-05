"""
gRPC client for the Waitlist Service.

The Claim Service (composite orchestrator) uses this module to communicate with
the Waitlist Service via gRPC on port 50053.

All functions raise HTTPException on known error codes (NOT_FOUND, ALREADY_EXISTS)
so callers can propagate them directly to HTTP responses.
Best-effort helpers (cancel/update) log on failure instead of raising.
"""
from __future__ import annotations

import logging
import os

import grpc
from dotenv import load_dotenv
from fastapi import HTTPException

import waitlist_pb2
import waitlist_pb2_grpc

load_dotenv()

WAITLIST_GRPC_HOST = os.getenv("WAITLIST_GRPC_HOST", "localhost")
WAITLIST_GRPC_PORT = os.getenv("WAITLIST_GRPC_PORT", "50053")
WAITLIST_GRPC_ADDR = f"{WAITLIST_GRPC_HOST}:{WAITLIST_GRPC_PORT}"

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0


async def join_waitlist(listing_id: int, charity_id: int, status: str = "WAITING") -> dict:
    """
    Charity joins the waitlist. Returns {listing_id, charity_id, position}.
    Raises HTTP 409 if already on the waitlist.
    Raises HTTP 503 if the Waitlist Service is unreachable.
    """
    try:
        async with grpc.aio.insecure_channel(WAITLIST_GRPC_ADDR) as channel:
            stub = waitlist_pb2_grpc.WaitlistServiceStub(channel)
            resp = await stub.JoinWaitlist(
                waitlist_pb2.JoinRequest(
                    listing_id=listing_id, charity_id=charity_id, status=status
                ),
                timeout=_TIMEOUT,
            )
        return {"listing_id": resp.listing_id, "charity_id": resp.charity_id, "position": resp.position}
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.ALREADY_EXISTS:
            raise HTTPException(status_code=409, detail="Already on the waitlist for this listing")
        if exc.code() == grpc.StatusCode.UNAVAILABLE:
            raise HTTPException(status_code=503, detail="Waitlist service unavailable")
        raise HTTPException(status_code=502, detail=f"Waitlist error: [{exc.code()}] {exc.details()}")


async def get_entries(listing_id: int, status: str = "") -> list[dict]:
    """
    Returns all entries (or filtered by status) for a listing.
    Pass status="" to fetch all; pass "WAITING", "QUEUING", etc. to filter.
    Raises HTTP 503 if unreachable.
    """
    try:
        async with grpc.aio.insecure_channel(WAITLIST_GRPC_ADDR) as channel:
            stub = waitlist_pb2_grpc.WaitlistServiceStub(channel)
            resp = await stub.GetEntries(
                waitlist_pb2.GetEntriesRequest(listing_id=listing_id, status=status),
                timeout=_TIMEOUT,
            )
        return [_proto_to_dict(e) for e in resp.entries]
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.UNAVAILABLE:
            raise HTTPException(status_code=503, detail="Waitlist service unavailable")
        raise HTTPException(status_code=502, detail=f"Waitlist error: [{exc.code()}] {exc.details()}")


async def get_waiting_entries(listing_id: int) -> list[dict]:
    """Returns WAITING entries ordered by rank/joined_at (FIFO). Used by try_promote_next."""
    return await get_entries(listing_id, status="WAITING")


async def get_queuing_entries(listing_id: int) -> list[dict]:
    """Returns QUEUING entries (in-window registrations, not yet ranked)."""
    return await get_entries(listing_id, status="QUEUING")


async def get_entry(listing_id: int, charity_id: int) -> dict | None:
    """
    Returns the single entry for a (listing, charity) pair, or None if not found.
    Raises HTTP 503 if unreachable.
    """
    try:
        async with grpc.aio.insecure_channel(WAITLIST_GRPC_ADDR) as channel:
            stub = waitlist_pb2_grpc.WaitlistServiceStub(channel)
            resp = await stub.GetEntry(
                waitlist_pb2.GetEntryRequest(listing_id=listing_id, charity_id=charity_id),
                timeout=_TIMEOUT,
            )
        return _proto_to_dict(resp)
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.NOT_FOUND:
            return None
        if exc.code() == grpc.StatusCode.UNAVAILABLE:
            raise HTTPException(status_code=503, detail="Waitlist service unavailable")
        raise HTTPException(status_code=502, detail=f"Waitlist error: [{exc.code()}] {exc.details()}")


async def leave_waitlist(listing_id: int, charity_id: int) -> None:
    """
    Charity voluntarily removes themselves (cancels WAITING/QUEUING entry).
    Raises HTTP 404 if the entry does not exist.
    Raises HTTP 503 if unreachable.
    """
    try:
        async with grpc.aio.insecure_channel(WAITLIST_GRPC_ADDR) as channel:
            stub = waitlist_pb2_grpc.WaitlistServiceStub(channel)
            await stub.LeaveWaitlist(
                waitlist_pb2.LeaveRequest(listing_id=listing_id, charity_id=charity_id),
                timeout=_TIMEOUT,
            )
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Not found on waitlist for this listing")
        if exc.code() == grpc.StatusCode.UNAVAILABLE:
            raise HTTPException(status_code=503, detail="Waitlist service unavailable")
        raise HTTPException(status_code=502, detail=f"Waitlist error: [{exc.code()}] {exc.details()}")


async def update_entry_status(entry_id: int, status: str) -> None:
    """
    Update a single entry's status by entry_id (e.g. OFFERED, CANCELLED).
    Best-effort: errors are logged rather than re-raised.
    """
    try:
        async with grpc.aio.insecure_channel(WAITLIST_GRPC_ADDR) as channel:
            stub = waitlist_pb2_grpc.WaitlistServiceStub(channel)
            await stub.UpdateEntryStatus(
                waitlist_pb2.UpdateStatusRequest(entry_id=entry_id, status=status),
                timeout=_TIMEOUT,
            )
    except grpc.aio.AioRpcError as exc:
        logger.warning("UpdateEntryStatus failed entry=%s → %s: [%s] %s",
                       entry_id, status, exc.code(), exc.details())


async def update_charity_entry(listing_id: int, charity_id: int, status: str) -> None:
    """
    Update an entry's status by (listing_id, charity_id) — used in approve_claim
    to mark the collecting charity's entry as COLLECTED.
    Best-effort: errors are logged but not re-raised.
    """
    try:
        async with grpc.aio.insecure_channel(WAITLIST_GRPC_ADDR) as channel:
            stub = waitlist_pb2_grpc.WaitlistServiceStub(channel)
            await stub.UpdateCharityEntry(
                waitlist_pb2.UpdateCharityEntryRequest(
                    listing_id=listing_id, charity_id=charity_id, status=status
                ),
                timeout=_TIMEOUT,
            )
    except grpc.aio.AioRpcError as exc:
        logger.warning("UpdateCharityEntry failed listing=%s charity=%s → %s: [%s] %s",
                       listing_id, charity_id, status, exc.code(), exc.details())


async def cancel_all_active_entries(listing_id: int) -> None:
    """
    Bulk-cancel all WAITING + QUEUING entries for a listing (item is SOLD).
    Best-effort: errors are logged but not re-raised.
    """
    try:
        async with grpc.aio.insecure_channel(WAITLIST_GRPC_ADDR) as channel:
            stub = waitlist_pb2_grpc.WaitlistServiceStub(channel)
            resp = await stub.CancelAllActive(
                waitlist_pb2.CancelAllRequest(listing_id=listing_id),
                timeout=_TIMEOUT,
            )
        logger.info("Cancelled %s active waitlist entries for listing %s",
                    resp.cancelled_count, listing_id)
    except grpc.aio.AioRpcError as exc:
        logger.warning("CancelAllActive failed for listing %s: [%s] %s",
                       listing_id, exc.code(), exc.details())


async def resolve_queue(listing_id: int, ranked_entries: list[dict]) -> None:
    """
    Sends ranked entries to the Waitlist Service to bulk-set rank/score/resolved_at
    and flip all QUEUING entries to WAITING.
    ranked_entries: list of {entry_id, rank, score}.
    Best-effort: errors are logged but not re-raised.
    """
    entries_proto = [
        waitlist_pb2.RankedEntry(entry_id=e["entry_id"], rank=e["rank"], score=e["score"])
        for e in ranked_entries
    ]
    try:
        async with grpc.aio.insecure_channel(WAITLIST_GRPC_ADDR) as channel:
            stub = waitlist_pb2_grpc.WaitlistServiceStub(channel)
            await stub.ResolveQueue(
                waitlist_pb2.ResolveQueueRequest(listing_id=listing_id, entries=entries_proto),
                timeout=_TIMEOUT,
            )
    except grpc.aio.AioRpcError as exc:
        logger.warning("ResolveQueue failed for listing %s: [%s] %s",
                       listing_id, exc.code(), exc.details())


def _proto_to_dict(proto: waitlist_pb2.WaitlistEntryProto) -> dict:
    return {
        "id":         proto.id,
        "listing_id": proto.listing_id,
        "charity_id": proto.charity_id,
        "joined_at":  proto.joined_at,
        "status":     proto.status,
        "position":   proto.position,
        "rank":       proto.rank or None,
        "score":      proto.score or None,
    }
