"""
Thin async gRPC client for the Verification Service — Payment Service subset.

Only exercises the two RPCs the Payment Service needs:
  - VerifyPublicUser   — block flagged/banned users before locking inventory.
  - RecordUserNoShow   — record a user no-show after a failed collection.
"""
from __future__ import annotations

import logging
import os

import grpc
from dotenv import load_dotenv

import verification_pb2
import verification_pb2_grpc

load_dotenv()

logger = logging.getLogger(__name__)

VERIFICATION_GRPC_HOST = os.getenv("VERIFICATION_GRPC_HOST", "localhost")
VERIFICATION_GRPC_PORT = os.getenv("VERIFICATION_GRPC_PORT", "50052")
VERIFICATION_GRPC_ADDR = f"{VERIFICATION_GRPC_HOST}:{VERIFICATION_GRPC_PORT}"

VERIFICATION_HTTP_URL = os.getenv("VERIFICATION_HTTP_URL", "http://verification-service:8009")


class UserNotEligibleError(Exception):
    """
    Raised when Verification Service confirms the user is ineligible (e.g. BANNED).
    Caller maps this to HTTP 403.
    """
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"User not eligible: {reason}")


async def verify_public_user(user_id: int, listing_id: int) -> None:
    """
    Calls VerifyPublicUser RPC.

    Returns:
        None — silent success means the user is eligible.

    Raises:
        UserNotEligibleError   — approved=False (e.g. "BANNED").
                                 Caller should return HTTP 403.
        HTTPException(503)     — gRPC UNAVAILABLE.
        HTTPException(502)     — any other gRPC error.
    """
    from fastapi import HTTPException

    async with grpc.aio.insecure_channel(VERIFICATION_GRPC_ADDR) as channel:
        stub = verification_pb2_grpc.VerificationServiceStub(channel)
        try:
            response = await stub.VerifyPublicUser(
                verification_pb2.VerifyUserRequest(
                    user_id=user_id,
                    listing_id=listing_id,
                )
            )
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNAVAILABLE:
                raise HTTPException(
                    status_code=503,
                    detail="Verification service unavailable — please retry",
                )
            raise HTTPException(
                status_code=502,
                detail=f"Verification error: [{exc.code()}] {exc.details()}",
            )

    if not response.approved:
        logger.warning(
            "User user_id=%s rejected for listing_id=%s reason=%s",
            user_id, listing_id, response.rejection_reason,
        )
        raise UserNotEligibleError(reason=response.rejection_reason)

    logger.info("User user_id=%s approved for listing_id=%s", user_id, listing_id)


async def record_user_noshow(user_id: int, transaction_id: str) -> None:
    """
    Calls RecordUserNoShow RPC.

    Best-effort: logs on any failure but never raises so the calling endpoint
    is not blocked by a transient verification service issue.
    """
    try:
        async with grpc.aio.insecure_channel(VERIFICATION_GRPC_ADDR) as channel:
            stub = verification_pb2_grpc.VerificationServiceStub(channel)
            response = await stub.RecordUserNoShow(
                verification_pb2.RecordUserNoShowRequest(
                    user_id=user_id,
                    transaction_id=transaction_id,
                )
            )
            logger.info(
                "User no-show recorded: user_id=%s transaction_id=%s total_noshows=%s",
                user_id, transaction_id, response.total_noshows,
            )
    except Exception as exc:
        logger.error(
            "Best-effort RecordUserNoShow failed for user_id=%s transaction_id=%s: %s",
            user_id, transaction_id, exc,
        )


async def record_user_late_cancel(user_id: int, transaction_id: str) -> None:
    """
    Calls the Verification Service REST endpoint to record a late-cancel attempt.

    Best-effort: logs on any failure so the 409 response to the user is not blocked.
    """
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{VERIFICATION_HTTP_URL}/user-late-cancel",
                json={"user_id": user_id, "transaction_id": transaction_id},
                timeout=5.0,
            )
            response.raise_for_status()
            logger.info(
                "User late-cancel recorded: user_id=%s transaction_id=%s",
                user_id, transaction_id,
            )
    except Exception as exc:
        logger.error(
            "Best-effort record_user_late_cancel failed for user_id=%s transaction_id=%s: %s",
            user_id, transaction_id, exc,
        )
