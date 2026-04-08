from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

# Injected via docker-compose environment variables
OUTSYSTEMS_API_URL = os.getenv("OUTSYSTEMS_API_URL", "")
OUTSYSTEMS_API_KEY = os.getenv("OUTSYSTEMS_API_KEY", "")

# Architecture contract: timeout → 503, never hang the claim flow
_TIMEOUT_SECONDS = float(os.getenv("OUTSYSTEMS_TIMEOUT_SECONDS", "5.0"))

class OutSystemsVerificationError(Exception):
    """Raised when OutSystems is unreachable or returns an unexpected status."""


async def check_charity_eligibility(
    charity_id: int,
    listing_id: int,
) -> tuple[bool, str]:
    """
    Calls the OutSystems REST endpoint to check waiver status.

    Returns:
        (approved, rejection_reason)
        approved=True, rejection_reason=""             → eligible
        approved=False, rejection_reason="MISSING_WAIVER" → rejected

    Raises:
        OutSystemsVerificationError — on timeout or non-200 response.
        Caller (grpc_server.py) maps this to gRPC UNAVAILABLE.
    """
    url = f"{OUTSYSTEMS_API_URL}/api/charity/verify" ##api/charity/verify a placeholder, to replace with real outsystems endpoint

    headers = {"X-API-Key": OUTSYSTEMS_API_KEY}
    payload = {"charityId": charity_id, "listingId": listing_id}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            data = response.json()
            approved: bool = data.get("approved", False)
            reason: str = "" if approved else data.get("rejectionReason", "MISSING_WAIVER")
            logger.info(
                "OutSystems check charity_id=%s listing_id=%s approved=%s reason=%s",
                charity_id,
                listing_id,
                approved,
                reason,
            )
            return approved, reason

        # OutSystems returned a non-200 — treat as transient failure
        logger.error(
            "OutSystems returned HTTP %s for charity_id=%s",
            response.status_code,
            charity_id,
        )
        raise OutSystemsVerificationError(
            f"OutSystems returned HTTP {response.status_code}"
        )

    except httpx.TimeoutException as exc:
        logger.error(
            "OutSystems timed out after %.1fs for charity_id=%s: %s",
            _TIMEOUT_SECONDS,
            charity_id,
            exc,
        )
        raise OutSystemsVerificationError("OutSystems request timed out") from exc

    except httpx.HTTPError as exc:
        logger.error("OutSystems HTTP error for charity_id=%s: %s", charity_id, exc)
        raise OutSystemsVerificationError(f"OutSystems HTTP error: {exc}") from exc