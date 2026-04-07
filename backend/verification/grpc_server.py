"""
Verification Service — async gRPC Servicer.

Business rules enforced (pure DB — no OutSystems calls):
  VerifyCharity    — cooldown/ban check (CharityStanding) + daily claim quota (CharityClaim)
  VerifyPublicUser — admin-set scalping flag check (PublicUserStanding)
  RecordNoShow     — insert no-show, upsert CharityStanding with escalating cooldown
  GetCharityStatus — full charity standing + live quota counts
  GetUserStatus    — full public user standing
  GetVendorStatus  — vendor NEA licence compliance state

OutSystems is the auth platform (login / JWT). This service never calls it.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import grpc
from sqlalchemy import func, select

import verification_pb2
import verification_pb2_grpc
from database import AsyncSessionLocal
from models import (
    AppealStatus,
    CharityClaim,
    CharityLateCancelWarning,
    CharityNoShow,
    CharityStanding,
    PublicUserNoShow,
    PublicUserStanding,
    VendorCompliance,
    noshows_window_start,
    today_start,
)

logger = logging.getLogger(__name__)

MAX_DAILY_CLAIMS    = int(os.getenv("MAX_DAILY_CLAIMS",    "5"))
MAX_NOSHOWS         = int(os.getenv("MAX_NOSHOWS",         "3"))
NOSHOWS_WINDOW_DAYS = int(os.getenv("NOSHOWS_WINDOW_DAYS", "30"))
BASE_COOLDOWN_DAYS  = int(os.getenv("BASE_COOLDOWN_DAYS",  "14"))


def _is_banned(standing: CharityStanding) -> bool:
    """
    Derive ban state from CharityStanding.

    A charity is banned when:
      - They have an active cooldown (cooldown_expires_at > now)
      - AND their appeal has not been approved

    Handles both timezone-aware (PostgreSQL) and naive (SQLite test) datetimes.
    """
    if standing.cooldown_expires_at is None:
        return False
    if standing.appeal_status == AppealStatus.APPROVED:
        return False
    expires = standing.cooldown_expires_at
    if expires.tzinfo is None:
        # SQLite stores without tz — treat as UTC
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc)


class VerificationServicer(verification_pb2_grpc.VerificationServiceServicer):

    # ── 1. Charity claim verification ─────────────────────────────────────────

    async def VerifyCharity(
        self,
        request: verification_pb2.VerifyRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.VerifyResponse:
        charity_id = request.charity_id
        listing_id = request.listing_id

        if charity_id <= 0 or listing_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "charity_id and listing_id must be > 0")
            return verification_pb2.VerifyResponse()

        logger.info("VerifyCharity: charity_id=%s listing_id=%s", charity_id, listing_id)

        try:
            async with AsyncSessionLocal() as db:
                # Check 1 — ban / active cooldown from CharityStanding
                standing_result = await db.execute(
                    select(CharityStanding).where(CharityStanding.charity_id == charity_id)
                )
                standing = standing_result.scalar_one_or_none()

                if standing is not None and _is_banned(standing):
                    logger.warning(
                        "Charity %s is in cooldown until %s (appeal_status=%s)",
                        charity_id, standing.cooldown_expires_at, standing.appeal_status,
                    )
                    return verification_pb2.VerifyResponse(
                        approved=False, rejection_reason="TOO_MANY_NOSHOWS"
                    )

                # Check 2 — daily hoarding quota (count today's active claims, excluding cancelled)
                quota_result = await db.execute(
                    select(func.count(CharityClaim.id)).where(
                        CharityClaim.charity_id == charity_id,
                        CharityClaim.created_at >= today_start(),
                        CharityClaim.is_cancelled == False,
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

                # Both checks passed — record the claim and approve
                db.add(CharityClaim(charity_id=charity_id, listing_id=listing_id))
                await db.commit()

        except Exception as exc:
            logger.exception("Unexpected error in VerifyCharity charity_id=%s: %s", charity_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.VerifyResponse()

        logger.info("Charity %s approved (claimed_today=%s)", charity_id, claimed_today + 1)
        return verification_pb2.VerifyResponse(approved=True, rejection_reason="")  

    # ── 2. Public user purchase verification ──────────────────────────────────

    async def VerifyPublicUser(
        self,
        request: verification_pb2.VerifyUserRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.VerifyResponse:
        user_id = request.user_id

        if user_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id must be > 0")
            return verification_pb2.VerifyResponse()

        logger.info("VerifyPublicUser: user_id=%s", user_id)

        try:
            async with AsyncSessionLocal() as db:
                standing_result = await db.execute(
                    select(PublicUserStanding).where(PublicUserStanding.user_id == user_id)
                )
                standing = standing_result.scalar_one_or_none()

                if standing is not None and standing.is_flagged:
                    logger.warning(
                        "User %s is flagged for scalping (reason=%s)", user_id, standing.flag_reason
                    )
                    return verification_pb2.VerifyResponse(
                        approved=False, rejection_reason="SCALPING_FLAG"
                    )

        except Exception as exc:
            logger.exception("Unexpected error in VerifyPublicUser user_id=%s: %s", user_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.VerifyResponse()

        logger.info("User %s approved (not flagged)", user_id)
        return verification_pb2.VerifyResponse(approved=True, rejection_reason="")

    # ── 3. Record a charity no-show ───────────────────────────────────────────

    async def RecordNoShow(
        self,
        request: verification_pb2.RecordNoShowRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.RecordNoShowResponse:
        charity_id = request.charity_id
        claim_id   = request.claim_id

        if charity_id <= 0 or claim_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "charity_id and claim_id must be > 0")
            return verification_pb2.RecordNoShowResponse()

        logger.info("RecordNoShow: charity_id=%s claim_id=%s", charity_id, claim_id)

        try:
            now          = datetime.now(timezone.utc)
            window_start = noshows_window_start(NOSHOWS_WINDOW_DAYS)

            async with AsyncSessionLocal() as db:
                # Insert the no-show record
                db.add(CharityNoShow(charity_id=charity_id, claim_id=claim_id))
                await db.flush()  # make it visible within this session for count queries

                # Count recent no-shows in rolling window (includes the one just inserted)
                recent_result = await db.execute(
                    select(func.count(CharityNoShow.id)).where(
                        CharityNoShow.charity_id == charity_id,
                        CharityNoShow.created_at >= window_start,
                    )
                )
                recent_noshows = recent_result.scalar()

                # Count lifetime no-shows
                lifetime_result = await db.execute(
                    select(func.count(CharityNoShow.id)).where(
                        CharityNoShow.charity_id == charity_id
                    )
                )
                total_noshows = lifetime_result.scalar()

                # Get or create CharityStanding
                standing_result = await db.execute(
                    select(CharityStanding).where(CharityStanding.charity_id == charity_id)
                )
                standing = standing_result.scalar_one_or_none()

                if standing is None:
                    standing = CharityStanding(
                        charity_id=charity_id,
                        warning_count=0,
                        ban_count=0,
                        appeal_status=AppealStatus.NONE,
                    )
                    db.add(standing)

                standing.last_noshow_at = now

                currently_banned = _is_banned(standing)

                if recent_noshows >= MAX_NOSHOWS and not currently_banned:
                    # Threshold reached and not already banned — trigger escalating cooldown
                    standing.ban_count += 1
                    days = BASE_COOLDOWN_DAYS * (2 ** (standing.ban_count - 1))
                    standing.cooldown_expires_at = now + timedelta(days=days)
                    standing.appeal_status = AppealStatus.NONE
                    logger.warning(
                        "Charity %s banned: ban_count=%s cooldown=%s days (expires %s)",
                        charity_id, standing.ban_count, days, standing.cooldown_expires_at,
                    )
                else:
                    # Below threshold OR already in cooldown — record as a warning
                    standing.warning_count += 1
                    if currently_banned:
                        logger.info(
                            "Charity %s got no-show while already banned — warning_count=%s",
                            charity_id, standing.warning_count,
                        )

                await db.commit()

        except Exception as exc:
            logger.exception("Unexpected error in RecordNoShow charity_id=%s: %s", charity_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.RecordNoShowResponse()

        logger.info(
            "No-show recorded for charity %s (recent=%s total=%s)",
            charity_id, recent_noshows, total_noshows,
        )
        return verification_pb2.RecordNoShowResponse(recorded=True, total_noshows=total_noshows)

    # ── 4. Cancel a charity claim (returns quota slot) ────────────────────────

    async def CancelClaim(
        self,
        request: verification_pb2.CancelClaimRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.CancelClaimResponse:
        charity_id = request.charity_id
        listing_id = request.listing_id

        if charity_id <= 0 or listing_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "charity_id and listing_id must be > 0")
            return verification_pb2.CancelClaimResponse()

        logger.info("CancelClaim: charity_id=%s listing_id=%s", charity_id, listing_id)

        try:
            async with AsyncSessionLocal() as db:
                # Find the most recent active (non-cancelled) claim for this charity+listing today
                result = await db.execute(
                    select(CharityClaim)
                    .where(
                        CharityClaim.charity_id == charity_id,
                        CharityClaim.listing_id == listing_id,
                        CharityClaim.is_cancelled == False,
                        CharityClaim.created_at >= today_start(),
                    )
                    .order_by(CharityClaim.created_at.desc())
                    .limit(1)
                )
                claim = result.scalar_one_or_none()

                if claim is None:
                    # Check whether the charity_id or listing_id is the unknown party
                    charity_exists = await db.execute(
                        select(CharityClaim).where(CharityClaim.charity_id == charity_id).limit(1)
                    )
                    if charity_exists.scalar_one_or_none() is None:
                        await context.abort(
                            grpc.StatusCode.NOT_FOUND,
                            f"No claims found for charity_id={charity_id}",
                        )
                        return verification_pb2.CancelClaimResponse()

                    listing_exists = await db.execute(
                        select(CharityClaim).where(
                            CharityClaim.charity_id == charity_id,
                            CharityClaim.listing_id == listing_id,
                        ).limit(1)
                    )
                    if listing_exists.scalar_one_or_none() is None:
                        await context.abort(
                            grpc.StatusCode.NOT_FOUND,
                            f"No claim found for charity_id={charity_id} with listing_id={listing_id}",
                        )
                        return verification_pb2.CancelClaimResponse()

                    # Both exist but no active claim today (already cancelled or from a prior day)
                    logger.warning(
                        "CancelClaim: claim exists but is already cancelled or not from today — charity=%s listing=%s",
                        charity_id, listing_id,
                    )
                    return verification_pb2.CancelClaimResponse(cancelled=False)

                claim.is_cancelled = True
                await db.commit()

        except Exception as exc:
            logger.exception("Unexpected error in CancelClaim charity_id=%s: %s", charity_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.CancelClaimResponse()

        logger.info("CancelClaim: quota slot returned for charity=%s listing=%s", charity_id, listing_id)
        return verification_pb2.CancelClaimResponse(cancelled=True)

    # ── 4b. Record a public user no-show (food wastage tracking) ─────────────

    async def RecordUserNoShow(
        self,
        request: verification_pb2.RecordUserNoShowRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.RecordUserNoShowResponse:
        user_id        = request.user_id
        transaction_id = request.transaction_id.strip()

        if user_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id must be > 0")
            return verification_pb2.RecordUserNoShowResponse()
        if not transaction_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "transaction_id must not be empty")
            return verification_pb2.RecordUserNoShowResponse()

        logger.info("RecordUserNoShow: user_id=%s transaction_id=%s", user_id, transaction_id)

        try:
            async with AsyncSessionLocal() as db:
                db.add(PublicUserNoShow(user_id=user_id, transaction_id=transaction_id))
                await db.flush()

                total_result = await db.execute(
                    select(func.count(PublicUserNoShow.id)).where(
                        PublicUserNoShow.user_id == user_id
                    )
                )
                total_noshows = total_result.scalar()
                await db.commit()

        except Exception as exc:
            logger.exception("Unexpected error in RecordUserNoShow user_id=%s: %s", user_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.RecordUserNoShowResponse()

        logger.info("User no-show recorded: user_id=%s total=%s", user_id, total_noshows)
        return verification_pb2.RecordUserNoShowResponse(recorded=True, total_noshows=total_noshows)

    # ── 5. Get full charity standing ──────────────────────────────────────────

    async def GetCharityStatus(
        self,
        request: verification_pb2.CharityStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.CharityStatusResponse:
        charity_id = request.charity_id

        if charity_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "charity_id must be > 0")
            return verification_pb2.CharityStatusResponse()

        logger.info("GetCharityStatus: charity_id=%s", charity_id)

        try:
            async with AsyncSessionLocal() as db:
                standing_result = await db.execute(
                    select(CharityStanding).where(CharityStanding.charity_id == charity_id)
                )
                standing = standing_result.scalar_one_or_none()

                # Live counts regardless of standing
                recent_result = await db.execute(
                    select(func.count(CharityNoShow.id)).where(
                        CharityNoShow.charity_id == charity_id,
                        CharityNoShow.created_at >= noshows_window_start(NOSHOWS_WINDOW_DAYS),
                    )
                )
                recent_noshows = recent_result.scalar()

                claim_result = await db.execute(
                    select(func.count(CharityClaim.id)).where(
                        CharityClaim.charity_id == charity_id,
                        CharityClaim.created_at >= today_start(),
                        CharityClaim.is_cancelled == False,
                    )
                )
                claimed_today = claim_result.scalar()

        except Exception as exc:
            logger.exception("Unexpected error in GetCharityStatus charity_id=%s: %s", charity_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.CharityStatusResponse()

        if standing is None:
            return verification_pb2.CharityStatusResponse(
                is_banned=False,
                ban_reason="",
                cooldown_until="",
                warning_count=0,
                recent_noshows=recent_noshows,
                claimed_today=claimed_today,
                appeal_status=AppealStatus.NONE.value,
            )

        banned       = _is_banned(standing)
        cooldown_str = standing.cooldown_expires_at.isoformat() if standing.cooldown_expires_at else ""

        return verification_pb2.CharityStatusResponse(
            is_banned=banned,
            ban_reason="TOO_MANY_NOSHOWS" if banned else "",
            cooldown_until=cooldown_str,
            warning_count=standing.warning_count,
            recent_noshows=recent_noshows,
            claimed_today=claimed_today,
            appeal_status=standing.appeal_status.value,
        )

    # ── 5. Get full public user standing ──────────────────────────────────────

    async def GetUserStatus(
        self,
        request: verification_pb2.UserStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.UserStatusResponse:
        user_id = request.user_id

        if user_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id must be > 0")
            return verification_pb2.UserStatusResponse()

        logger.info("GetUserStatus: user_id=%s", user_id)

        try:
            async with AsyncSessionLocal() as db:
                standing_result = await db.execute(
                    select(PublicUserStanding).where(PublicUserStanding.user_id == user_id)
                )
                standing = standing_result.scalar_one_or_none()

                noshow_result = await db.execute(
                    select(func.count(PublicUserNoShow.id)).where(
                        PublicUserNoShow.user_id == user_id
                    )
                )
                total_noshows = noshow_result.scalar()

        except Exception as exc:
            logger.exception("Unexpected error in GetUserStatus user_id=%s: %s", user_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.UserStatusResponse()

        if standing is None:
            return verification_pb2.UserStatusResponse(
                is_flagged=False,
                flag_reason="",
                flag_count=0,
                total_noshows=total_noshows,
            )

        return verification_pb2.UserStatusResponse(
            is_flagged=standing.is_flagged,
            flag_reason=standing.flag_reason or "",
            flag_count=standing.flag_count,
            total_noshows=total_noshows,
        )

    # ── 6. Get vendor compliance status ───────────────────────────────────────

    async def GetVendorStatus(
        self,
        request: verification_pb2.VendorStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.VendorStatusResponse:
        vendor_id = request.vendor_id

        if vendor_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "vendor_id must be > 0")
            return verification_pb2.VendorStatusResponse()

        logger.info("GetVendorStatus: vendor_id=%s", vendor_id)

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(VendorCompliance).where(VendorCompliance.vendor_id == vendor_id)
                )
                compliance = result.scalar_one_or_none()

        except Exception as exc:
            logger.exception("Unexpected error in GetVendorStatus vendor_id=%s: %s", vendor_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.VendorStatusResponse()

        if compliance is None:
            # No record → assume compliant (vendors are compliant until flagged)
            return verification_pb2.VendorStatusResponse(
                is_compliant=True,
                compliance_flag="",
                license_expires_at="",
            )

        # Derived compliance: db flag AND (no expiry set OR expiry is in the future)
        now       = datetime.now(timezone.utc)
        lic_dt    = compliance.license_expires_at
        if lic_dt is not None and lic_dt.tzinfo is None:
            lic_dt = lic_dt.replace(tzinfo=timezone.utc)
        license_ok = lic_dt is None or lic_dt > now
        effective_compliant = compliance.is_compliant and license_ok
        expires_str = lic_dt.isoformat() if lic_dt else ""

        # Derive compliance_flag: prefer explicit admin flag; fall back to LICENSE_EXPIRED
        if compliance.compliance_flag:
            derived_flag = compliance.compliance_flag
        elif not license_ok:
            derived_flag = "LICENSE_EXPIRED"
        else:
            derived_flag = ""

        return verification_pb2.VendorStatusResponse(
            is_compliant=effective_compliant,
            compliance_flag=derived_flag,
            license_expires_at=expires_str,
        )

    # ── 7. Get charity score for queue ranking ────────────────────────────────

    async def GetCharityScore(
        self,
        request: verification_pb2.CharityScoreRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.CharityScoreResponse:
        charity_id = request.charity_id

        if charity_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "charity_id must be > 0")
            return verification_pb2.CharityScoreResponse()

        logger.info("GetCharityScore: charity_id=%s", charity_id)

        try:
            async with AsyncSessionLocal() as db:
                # Count today's non-cancelled claims (fairness: deprioritise charities who
                # already received food today; 5 claims/day is the max enforced by VerifyCharity)
                completed_result = await db.execute(
                    select(func.count(CharityClaim.id)).where(
                        CharityClaim.charity_id == charity_id,
                        CharityClaim.created_at >= today_start(),
                        CharityClaim.is_cancelled == False,
                    )
                )
                today_completed = completed_result.scalar() or 0

                noshow_result = await db.execute(
                    select(func.count(CharityNoShow.id)).where(
                        CharityNoShow.charity_id == charity_id
                    )
                )
                noshow_count = noshow_result.scalar() or 0

        except Exception as exc:
            logger.exception("Unexpected error in GetCharityScore charity_id=%s: %s", charity_id, exc)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.CharityScoreResponse()

        # Higher score = higher queue priority.
        # Penalty for claims already made today (-1 per claim): charities who haven't gotten
        # food yet rank above those who have.
        # Penalty for lifetime no-shows (-2 each): unreliable charities rank lower.
        score = -today_completed - (noshow_count * 2)
        logger.info(
            "GetCharityScore: charity_id=%s today_completed=%s noshows=%s score=%s",
            charity_id, today_completed, noshow_count, score,
        )
        return verification_pb2.CharityScoreResponse(
            completed_claims=today_completed,
            noshow_count=noshow_count,
            score=score,
        )

    # ── 8. Record a late-cancel warning ───────────────────────────────────────

    async def RecordLateCancelWarning(
        self,
        request: verification_pb2.LateCancelRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.LateCancelResponse:
        """
        Called by Claim Service when a charity cancels after the grace window.

        Persists a row to charity_late_cancel_warnings (append-only log) and
        increments CharityStanding.warning_count so the standing check reflects it.
        """
        charity_id = request.charity_id
        claim_id   = request.claim_id

        if charity_id <= 0 or claim_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "charity_id and claim_id must be > 0")
            return verification_pb2.LateCancelResponse()

        logger.warning(
            "RecordLateCancelWarning: charity_id=%s claim_id=%s", charity_id, claim_id
        )

        try:
            async with AsyncSessionLocal() as db:
                # Append the warning record
                db.add(CharityLateCancelWarning(charity_id=charity_id, claim_id=claim_id))
                await db.flush()

                # Total late-cancel warnings for this charity
                total_result = await db.execute(
                    select(func.count(CharityLateCancelWarning.id)).where(
                        CharityLateCancelWarning.charity_id == charity_id
                    )
                )
                total_late_cancels = total_result.scalar()

                # Upsert CharityStanding.warning_count
                standing_result = await db.execute(
                    select(CharityStanding).where(CharityStanding.charity_id == charity_id)
                )
                standing = standing_result.scalar_one_or_none()
                if standing is None:
                    standing = CharityStanding(
                        charity_id=charity_id,
                        warning_count=1,
                        ban_count=0,
                        appeal_status=AppealStatus.NONE,
                    )
                    db.add(standing)
                else:
                    standing.warning_count += 1

                await db.commit()

        except Exception as exc:
            logger.exception(
                "Unexpected error in RecordLateCancelWarning charity_id=%s: %s", charity_id, exc
            )
            await context.abort(grpc.StatusCode.INTERNAL, "Internal verification error")
            return verification_pb2.LateCancelResponse()

        logger.warning(
            "Late-cancel warning recorded: charity_id=%s claim_id=%s total_warnings=%s",
            charity_id, claim_id, total_late_cancels,
        )
        return verification_pb2.LateCancelResponse(
            recorded=True,
            late_cancel_count=total_late_cancels,
        )


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
