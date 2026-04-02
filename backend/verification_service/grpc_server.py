"""
Verification Service — async gRPC Servicer.

Business rules enforced (pure DB — no OutSystems calls):
  VerifyCharity    — daily claim quota (anti-hoarding) + rolling no-show pattern check
  VerifyPublicUser — daily purchase quota (anti-scalping)
  RecordNoShow     — insert a no-show record when a charity fails to collect

OutSystems is the auth platform (login / JWT). This service never calls it.
"""
from __future__ import annotations

import logging
import os

import grpc
from sqlalchemy import func, select

import verification_pb2
import verification_pb2_grpc
from database import (
    AsyncSessionLocal,
    CharityClaim,
    CharityNoShow,
    PublicUserPurchase,
    noshows_window_start,
    today_start,
)

logger = logging.getLogger(__name__)

MAX_DAILY_CLAIMS    = int(os.getenv("MAX_DAILY_CLAIMS",    "5"))   # anti-hoarding limit per charity
MAX_DAILY_PURCHASES = int(os.getenv("MAX_DAILY_PURCHASES", "3"))   # anti-scalping limit per user
MAX_NOSHOWS         = int(os.getenv("MAX_NOSHOWS",         "3"))   # no-shows before temporary ban
NOSHOWS_WINDOW_DAYS = int(os.getenv("NOSHOWS_WINDOW_DAYS", "30"))  # rolling window in days


class VerificationServicer(verification_pb2_grpc.VerificationServiceServicer):

    # ── 1. Charity claim verification ─────────────────────────────────────────

    async def VerifyCharity(
        self,
        request: verification_pb2.VerifyRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.VerifyResponse:
        charity_id = request.charity_id
        listing_id = request.listing_id
        logger.info("VerifyCharity: charity_id=%s listing_id=%s", charity_id, listing_id)

        try:
            async with AsyncSessionLocal() as db:
                # Check 1 — daily hoarding quota
                quota_result = await db.execute(
                    select(func.count(CharityClaim.id)).where(
                        CharityClaim.charity_id == charity_id,
                        CharityClaim.created_at >= today_start(),
                    )
                )
                claimed_today = quota_result.scalar()

            if claimed_today >= MAX_DAILY_CLAIMS:
                logger.warning(
                    "Charity %s quota exceeded (%s/%s today)",
                    charity_id, claimed_today, MAX_DAILY_CLAIMS,
                )
                return verification_pb2.VerifyResponse(
                    approved=False, rejection_reason="QUOTA_EXCEEDED"
                )

            async with AsyncSessionLocal() as db:
                # Check 2 — no-show pattern (rolling window)
                noshow_result = await db.execute(
                    select(func.count(CharityNoShow.id)).where(
                        CharityNoShow.charity_id == charity_id,
                        CharityNoShow.created_at >= noshows_window_start(NOSHOWS_WINDOW_DAYS),
                    )
                )
                recent_noshows = noshow_result.scalar()

            if recent_noshows >= MAX_NOSHOWS:
                logger.warning(
                    "Charity %s has %s no-shows in last %s days — rejected",
                    charity_id, recent_noshows, NOSHOWS_WINDOW_DAYS,
                )
                return verification_pb2.VerifyResponse(
                    approved=False, rejection_reason="TOO_MANY_NOSHOWS"
                )

            # Both checks passed — record the claim and approve
            async with AsyncSessionLocal() as db:
                db.add(CharityClaim(charity_id=charity_id, listing_id=listing_id))
                await db.commit()

        except Exception as exc:
            logger.exception("Unexpected error in VerifyCharity charity_id=%s: %s", charity_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.VerifyResponse()

        logger.info(
            "Charity %s approved (%s/%s today, %s no-shows in last %s days)",
            charity_id, claimed_today + 1, MAX_DAILY_CLAIMS, recent_noshows, NOSHOWS_WINDOW_DAYS,
        )
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

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(func.count(PublicUserPurchase.id)).where(
                        PublicUserPurchase.user_id == user_id,
                        PublicUserPurchase.created_at >= today_start(),
                    )
                )
                purchases_today = result.scalar()

            if purchases_today >= MAX_DAILY_PURCHASES:
                logger.warning(
                    "User %s purchase quota exceeded (%s/%s today)",
                    user_id, purchases_today, MAX_DAILY_PURCHASES,
                )
                return verification_pb2.VerifyResponse(
                    approved=False, rejection_reason="PURCHASE_QUOTA_EXCEEDED"
                )

            async with AsyncSessionLocal() as db:
                db.add(PublicUserPurchase(user_id=user_id, listing_id=listing_id))
                await db.commit()

        except Exception as exc:
            logger.exception("Unexpected error in VerifyPublicUser user_id=%s: %s", user_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.VerifyResponse()

        logger.info("User %s approved (%s/%s purchases today)", user_id, purchases_today + 1, MAX_DAILY_PURCHASES)
        return verification_pb2.VerifyResponse(approved=True, rejection_reason="")

    # ── 3. Record a charity no-show ───────────────────────────────────────────

    async def RecordNoShow(
        self,
        request: verification_pb2.RecordNoShowRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.RecordNoShowResponse:
        charity_id = request.charity_id
        claim_id   = request.claim_id
        logger.info("RecordNoShow: charity_id=%s claim_id=%s", charity_id, claim_id)

        try:
            async with AsyncSessionLocal() as db:
                db.add(CharityNoShow(charity_id=charity_id, claim_id=claim_id))
                await db.commit()

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(func.count(CharityNoShow.id)).where(
                        CharityNoShow.charity_id == charity_id,
                    )
                )
                total = result.scalar()

        except Exception as exc:
            logger.exception("Unexpected error in RecordNoShow charity_id=%s: %s", charity_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.RecordNoShowResponse()

        logger.info("No-show recorded for charity %s (lifetime total: %s)", charity_id, total)
        return verification_pb2.RecordNoShowResponse(recorded=True, total_noshows=total)


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
