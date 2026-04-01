"""
Thin async gRPC client for the Verification Service.
Called during POST /claims to check charity eligibility via OutSystems
before locking inventory.

Mirrors the pattern of inventory_client.py.
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


class CharityNotEligibleError(Exception):
    """
    Raised when OutSystems confirms the charity is ineligible.
    Carries the rejection_reason string (e.g. "MISSING_WAIVER").
    Caller maps this to HTTP 403.
    """
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Charity not eligible: {reason}")


async def verify_charity(charity_id: int, listing_id: int) -> None:
    """
    Calls VerifyCharity RPC on the Verification Service.

    Returns:
        None — silent success means the charity is eligible.

    Raises:
        CharityNotEligibleError  — approved=False (e.g. MISSING_WAIVER).
                                   Caller should return HTTP 403.
        HTTPException(503)       — gRPC UNAVAILABLE, OutSystems is down.
                                   Raised directly so FastAPI handles it.
        HTTPException(502)       — any other gRPC error.
    """
    from fastapi import HTTPException

    async with grpc.aio.insecure_channel(VERIFICATION_GRPC_ADDR) as channel:
        stub = verification_pb2_grpc.VerificationServiceStub(channel)

        try:
            response = await stub.VerifyCharity(
                verification_pb2.VerifyRequest(
                    charity_id=charity_id,
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
            "Charity charity_id=%s rejected for listing_id=%s reason=%s",
            charity_id,
            listing_id,
            response.rejection_reason,
        )
        raise CharityNotEligibleError(reason=response.rejection_reason)

    logger.info(
        "Charity charity_id=%s approved for listing_id=%s",
        charity_id,
        listing_id,
    )
