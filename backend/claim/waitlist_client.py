"""
HTTP client for the Waitlist Service.

The Claim Service (composite orchestrator) uses this module to:
  - Proxy join / view / leave requests from charity-facing endpoints.
  - Fetch WAITING entries and update their status inside try_promote_next.

All functions raise HTTPException on known error codes so callers can propagate
them directly to their own HTTP responses.  PATCH (update_entry_status) is
best-effort: errors are logged rather than re-raised so that a status-update
failure never aborts a successful promotion.
"""
import logging
import os

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

WAITLIST_SERVICE_URL = os.getenv("WAITLIST_SERVICE_URL", "http://localhost:8010")

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0  # seconds


async def join_waitlist(listing_id: int, charity_id: int) -> dict:
    """
    Join the waitlist for a listing.
    Returns a WaitlistPosition dict: {listing_id, charity_id, position}.
    Raises HTTPException 409 if already on the waitlist.
    Raises HTTPException 503 if the Waitlist Service is unreachable.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{WAITLIST_SERVICE_URL}/waitlist/{listing_id}/entries",
                json={"charity_id": charity_id},
            )
        if resp.status_code == 409:
            raise HTTPException(status_code=409, detail="Already on the waitlist for this listing")
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Waitlist service unavailable: {exc}")


async def get_waiting_entries(listing_id: int) -> list[dict]:
    """
    Returns all WAITING entries for a listing ordered FIFO by join time.
    Each dict: {id, listing_id, charity_id, joined_at, status, position}.
    Used by try_promote_next to walk the queue.
    Raises HTTPException 503 if the Waitlist Service is unreachable.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{WAITLIST_SERVICE_URL}/waitlist/{listing_id}/entries",
                params={"status": "WAITING"},
            )
        resp.raise_for_status()
        return resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Waitlist service unavailable: {exc}")


async def get_entries(listing_id: int) -> list[dict]:
    """
    Returns all entries (any status) for a listing — for display on the charity dashboard.
    Raises HTTPException 503 if the Waitlist Service is unreachable.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{WAITLIST_SERVICE_URL}/waitlist/{listing_id}/entries",
            )
        resp.raise_for_status()
        return resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Waitlist service unavailable: {exc}")


async def leave_waitlist(listing_id: int, charity_id: int) -> None:
    """
    Remove a charity from the waitlist.
    Raises HTTPException 404 if the entry does not exist.
    Raises HTTPException 503 if the Waitlist Service is unreachable.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.delete(
                f"{WAITLIST_SERVICE_URL}/waitlist/{listing_id}/entries/{charity_id}",
            )
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Not found on waitlist for this listing")
        resp.raise_for_status()
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Waitlist service unavailable: {exc}")


async def update_entry_status(entry_id: int, status: str) -> None:
    """
    Mark an entry as PROMOTED or CANCELLED.
    Best-effort: errors are only logged so a status-update failure never
    aborts a successful promotion in try_promote_next.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.patch(
                f"{WAITLIST_SERVICE_URL}/waitlist/entries/{entry_id}",
                json={"status": status},
            )
        resp.raise_for_status()
    except httpx.RequestError as exc:
        logger.warning("Failed to update waitlist entry %s → %s: %s", entry_id, status, exc)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Waitlist entry %s status update returned %s: %s",
            entry_id, exc.response.status_code, exc,
        )
