"""
OutSystems HTTP client for the Verification Service.

Covers three eligibility checks — one per gRPC RPC:
  check_charity_eligibility  — called by VerifyCharity
  check_user_eligibility     — called by VerifyPublicUser
  check_vendor_compliance    — called by CheckVendorCompliance

Mock mode (MOCK_OUTSYSTEMS=true) skips all HTTP calls, returning configurable
approved/rejected responses.  Set MOCK_OUTSYSTEMS_APPROVED=true/false to
control the mock result.  Required for local dev without a real OutSystems env.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

OUTSYSTEMS_API_URL = os.getenv("OUTSYSTEMS_API_URL", "")
OUTSYSTEMS_API_KEY = os.getenv("OUTSYSTEMS_API_KEY", "")
_TIMEOUT_SECONDS   = float(os.getenv("OUTSYSTEMS_TIMEOUT_SECONDS", "5.0"))
MOCK_OUTSYSTEMS    = os.getenv("MOCK_OUTSYSTEMS", "false").lower() == "true"
MOCK_OUTSYSTEMS_APPROVED = os.getenv("MOCK_OUTSYSTEMS_APPROVED", "true").lower() == "true"

_HEADERS = {"X-API-Key": OUTSYSTEMS_API_KEY}


class OutSystemsVerificationError(Exception):
    """Raised when OutSystems is unreachable or returns an unexpected status."""


# ── Shared HTTP helper ────────────────────────────────────────────────────────

async def _post(path: str, payload: dict) -> dict:
    """POST to OutSystems and return the parsed JSON body.

    Raises:
        OutSystemsVerificationError — on timeout, HTTP error, or non-200 response.
    """
    url = f"{OUTSYSTEMS_API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=_HEADERS)

        if response.status_code == 200:
            return response.json()

        logger.error("OutSystems %s returned HTTP %s", path, response.status_code)
        raise OutSystemsVerificationError(f"OutSystems returned HTTP {response.status_code}")

    except httpx.TimeoutException as exc:
        logger.error("OutSystems %s timed out after %.1fs: %s", path, _TIMEOUT_SECONDS, exc)
        raise OutSystemsVerificationError("OutSystems request timed out") from exc

    except httpx.HTTPError as exc:
        logger.error("OutSystems %s HTTP error: %s", path, exc)
        raise OutSystemsVerificationError(f"OutSystems HTTP error: {exc}") from exc


# ── Public functions ──────────────────────────────────────────────────────────

async def check_charity_eligibility(charity_id: int, listing_id: int) -> tuple[bool, str]:
    """
    Verifies charity registration + indemnity waiver status via OutSystems.

    Returns:
        (True, "")                     — eligible.
        (False, "MISSING_WAIVER")      — rejected; reason from OutSystems.

    Raises:
        OutSystemsVerificationError — network failure or non-200 response.
    """
    if MOCK_OUTSYSTEMS:
        approved = MOCK_OUTSYSTEMS_APPROVED
        reason   = "" if approved else "MISSING_WAIVER"
        logger.info("MOCK VerifyCharity charity_id=%s approved=%s", charity_id, approved)
        return approved, reason

    data = await _post("/api/charity/verify", {"charityId": charity_id, "listingId": listing_id})
    approved: bool = data.get("approved", False)
    reason:   str  = "" if approved else data.get("rejectionReason", "MISSING_WAIVER")
    logger.info("OutSystems VerifyCharity charity_id=%s approved=%s reason=%s", charity_id, approved, reason)
    return approved, reason


async def check_user_eligibility(user_id: int, listing_id: int) -> tuple[bool, str]:
    """
    Verifies public user has accepted consumer indemnity terms via OutSystems.

    Returns:
        (True, "")                          — eligible.
        (False, "NO_CONSUMER_INDEMNITY")    — user has not signed indemnity.

    Raises:
        OutSystemsVerificationError — network failure.
    """
    if MOCK_OUTSYSTEMS:
        approved = MOCK_OUTSYSTEMS_APPROVED
        reason   = "" if approved else "NO_CONSUMER_INDEMNITY"
        logger.info("MOCK VerifyPublicUser user_id=%s approved=%s", user_id, approved)
        return approved, reason

    data = await _post("/api/user/verify", {"userId": user_id, "listingId": listing_id})
    approved: bool = data.get("approved", False)
    reason:   str  = "" if approved else data.get("rejectionReason", "NO_CONSUMER_INDEMNITY")
    logger.info("OutSystems VerifyPublicUser user_id=%s approved=%s reason=%s", user_id, approved, reason)
    return approved, reason


async def check_vendor_compliance(vendor_id: int) -> tuple[bool, str]:
    """
    Checks vendor NEA / food-safety license status via OutSystems.

    Returns:
        (True, "")                     — compliant.
        (False, "NEA_LICENSE_EXPIRED") — license has lapsed.

    Raises:
        OutSystemsVerificationError — network failure.
    """
    if MOCK_OUTSYSTEMS:
        approved = MOCK_OUTSYSTEMS_APPROVED
        reason   = "" if approved else "NEA_LICENSE_EXPIRED"
        logger.info("MOCK CheckVendorCompliance vendor_id=%s approved=%s", vendor_id, approved)
        return approved, reason

    data = await _post("/api/vendor/compliance", {"vendorId": vendor_id})
    approved: bool = data.get("approved", False)
    reason:   str  = "" if approved else data.get("rejectionReason", "NEA_LICENSE_EXPIRED")
    logger.info("OutSystems CheckVendorCompliance vendor_id=%s approved=%s reason=%s", vendor_id, approved, reason)
    return approved, reason
