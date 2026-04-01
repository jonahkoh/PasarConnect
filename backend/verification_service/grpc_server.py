"""
Verification Service — async gRPC Servicer.

Implements all three RPCs defined in verification.proto.

Each RPC follows the same three-step pattern:
  1. Call OutSystems REST (via outsystems_client) to check legal status.
  2. Query the local PostgreSQL quota table to enforce daily limits.
  3. If eligible, INSERT a quota row and return approved=True.

Error mapping:
  OutSystemsVerificationError → gRPC UNAVAILABLE (503 equivalent)
  Any unexpected exception     → gRPC INTERNAL   (500 equivalent)
"""
from __future__ import annotations

import logging
import os

import grpc
from sqlalchemy import func, select

import verification_pb2
import verification_pb2_grpc
from database import AsyncSessionLocal, CharityClaim, PublicUserPurchase, today_start
from outsystems_client import (
    OutSystemsVerificationError,
    check_charity_eligibility,
    check_user_eligibility,
    check_vendor_compliance,
)

logger = logging.getLogger(__name__)

MAX_DAILY_CLAIMS    = int(os.getenv("MAX_DAILY_CLAIMS",    "5"))  # charity hoarding limit
MAX_DAILY_PURCHASES = int(os.getenv("MAX_DAILY_PURCHASES", "3"))  # public anti-scalping limit


class VerificationServicer(verification_pb2_grpc.VerificationServiceServicer):
    """
    Implements VerificationService from verification.proto.

    Server is started by main.py inside the FastAPI lifespan so it shares
    the same asyncio event loop.
    """

    # ── 1. Charity claim verification ─────────────────────────────────────────

    async def VerifyCharity(
        self,
        request: verification_pb2.VerifyRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.VerifyResponse:
        charity_id = request.charity_id
        listing_id = request.listing_id
        logger.info("VerifyCharity: charity_id=%s listing_id=%s", charity_id, listing_id)

        # Step 1 — OutSystems legal check (registration + indemnity waiver)
        try:
            approved, reason = await check_charity_eligibility(charity_id, listing_id)
        except OutSystemsVerificationError as exc:
            logger.error("OutSystems unavailable for charity_id=%s: %s", charity_id, exc)
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                f"Verification service unavailable: {exc}",
            )
            return verification_pb2.VerifyResponse()
        except Exception as exc:
            logger.exception("Unexpected error in VerifyCharity charity_id=%s: %s", charity_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.VerifyResponse()

        if not approved:
            logger.warning("Charity %s rejected by OutSystems: %s", charity_id, reason)
            return verification_pb2.VerifyResponse(approved=False, rejection_reason=reason)

        # Step 2 — Daily hoarding-quota check
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(func.count(CharityClaim.id)).where(
                    CharityClaim.charity_id == charity_id,
                    CharityClaim.created_at >= today_start(),
                )
            )
            count = result.scalar()

        if count >= MAX_DAILY_CLAIMS:
            logger.warning(
                "Charity %s exceeded daily quota (%s/%s)", charity_id, count, MAX_DAILY_CLAIMS
            )
            return verification_pb2.VerifyResponse(
                approved=False, rejection_reason="QUOTA_EXCEEDED"
            )

        # Step 3 — Record the approved claim and return success
        async with AsyncSessionLocal() as db:
            db.add(CharityClaim(charity_id=charity_id, listing_id=listing_id))
            await db.commit()

        logger.info("Charity %s approved (%s/%s today)", charity_id, count + 1, MAX_DAILY_CLAIMS)
        return verification_pb2.VerifyResponse(approved=True, rejection_reason="")

    # ── 2. Public user purchase verification ──────────────────────────────────

    async def VerifyPublicUser(
        self,
        request: verification_pb2.VerifyUserRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.VerifyResponse:
        user_id    = request.user_id
        listing_id = request.listing_id
        logger.info("VerifyPublicUser: user_id=%s listing_id=%s", user_id, listing_id)

        # Step 1 — OutSystems consumer indemnity check
        try:
            approved, reason = await check_user_eligibility(user_id, listing_id)
        except OutSystemsVerificationError as exc:
            logger.error("OutSystems unavailable for user_id=%s: %s", user_id, exc)
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                f"Verification service unavailable: {exc}",
            )
            return verification_pb2.VerifyResponse()
        except Exception as exc:
            logger.exception("Unexpected error in VerifyPublicUser user_id=%s: %s", user_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.VerifyResponse()

        if not approved:
            logger.warning("User %s rejected by OutSystems: %s", user_id, reason)
            return verification_pb2.VerifyResponse(approved=False, rejection_reason=reason)

        # Step 2 — Daily anti-scalping quota check
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(func.count(PublicUserPurchase.id)).where(
                    PublicUserPurchase.user_id == user_id,
                    PublicUserPurchase.created_at >= today_start(),
                )
            )
            count = result.scalar()

        if count >= MAX_DAILY_PURCHASES:
            logger.warning(
                "User %s exceeded daily purchase quota (%s/%s)", user_id, count, MAX_DAILY_PURCHASES
            )
            return verification_pb2.VerifyResponse(
                approved=False, rejection_reason="PURCHASE_QUOTA_EXCEEDED"
            )

        # Step 3 — Record the approved purchase and return success
        async with AsyncSessionLocal() as db:
            db.add(PublicUserPurchase(user_id=user_id, listing_id=listing_id))
            await db.commit()

        logger.info(
            "User %s approved (%s/%s purchases today)", user_id, count + 1, MAX_DAILY_PURCHASES
        )
        return verification_pb2.VerifyResponse(approved=True, rejection_reason="")

    # ── 3. Vendor NEA compliance check ────────────────────────────────────────

    async def CheckVendorCompliance(
        self,
        request: verification_pb2.VendorComplianceRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.VerifyResponse:
        vendor_id = request.vendor_id
        logger.info("CheckVendorCompliance: vendor_id=%s", vendor_id)

        # No local quota table — just delegate to OutSystems license check
        try:
            approved, reason = await check_vendor_compliance(vendor_id)
        except OutSystemsVerificationError as exc:
            logger.error("OutSystems unavailable for vendor_id=%s: %s", vendor_id, exc)
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                f"Verification service unavailable: {exc}",
            )
            return verification_pb2.VerifyResponse()
        except Exception as exc:
            logger.exception(
                "Unexpected error in CheckVendorCompliance vendor_id=%s: %s", vendor_id, exc
            )
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.VerifyResponse()

        if not approved:
            logger.warning("Vendor %s not compliant: %s", vendor_id, reason)
            return verification_pb2.VerifyResponse(approved=False, rejection_reason=reason)

        logger.info("Vendor %s compliance OK", vendor_id)
        return verification_pb2.VerifyResponse(approved=True, rejection_reason="")


# ── Server factory ────────────────────────────────────────────────────────────

async def start_grpc_server(host: str = "0.0.0.0", port: int = 50052) -> grpc.aio.Server:
    server = grpc.aio.server()
    verification_pb2_grpc.add_VerificationServiceServicer_to_server(
        VerificationServicer(), server
    )
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    logger.info("Verification gRPC server listening on %s:%s", host, port)
    return server
