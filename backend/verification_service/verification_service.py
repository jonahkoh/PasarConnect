"""
PasarConnect Verification Service (Port: 50052)

Three verification flows:
1. VerifyCharity      - Claim Service    : registration + indemnity + daily hoarding quota
2. VerifyPublicUser   - Payment Service  : consumer indemnity + daily anti-scalping quota
3. CheckVendorCompliance - Inventory Service : NEA Hygiene license status
"""
import asyncio
import os
import grpc
import logging
from concurrent import futures
from datetime import datetime

import httpx
from sqlalchemy import Column, Integer, DateTime, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base

import verification_pb2
import verification_pb2_grpc

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
DATABASE_URL        = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost/verification_db")
OUTSYSTEMS_URL      = os.getenv("OUTSYSTEMS_URL", "http://localhost:8080")
OUTSYSTEMS_TOKEN    = os.getenv("OUTSYSTEMS_TOKEN", "demo-token")
MAX_DAILY_CLAIMS    = int(os.getenv("MAX_DAILY_CLAIMS", "5"))     # charity hoarding limit
MAX_DAILY_PURCHASES = int(os.getenv("MAX_DAILY_PURCHASES", "3"))  # public anti-scalping limit
GRPC_PORT           = os.getenv("GRPC_PORT", "50052")

# Database
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


class CharityClaim(Base):
    """Tracks charity claim attempts for daily hoarding quota."""
    __tablename__ = "charity_claims"
    id         = Column(Integer, primary_key=True)
    charity_id = Column(Integer, index=True)
    listing_id = Column(Integer)
    created_at = Column(DateTime, default=func.now())


class PublicUserPurchase(Base):
    """Tracks public user purchase attempts for daily anti-scalping quota."""
    __tablename__ = "public_user_purchases"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, index=True)
    listing_id = Column(Integer)
    created_at = Column(DateTime, default=func.now())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today_start() -> datetime:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


async def _outsystems_get(client: httpx.AsyncClient, path: str) -> dict | None:
    """GET from OutSystems. Returns parsed JSON or None on network failure."""
    try:
        resp = await client.get(
            f"{OUTSYSTEMS_URL}{path}",
            headers={
                "Authorization": f"Bearer {OUTSYSTEMS_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.RequestError as e:
        logger.error("OutSystems request failed (%s): %s", path, e)
        return None


# ── gRPC Servicer ─────────────────────────────────────────────────────────────

class VerificationService(verification_pb2_grpc.VerificationServicer):

    # ── 1. Charity claim verification ─────────────────────────────────────────
    async def VerifyCharity(self, request, context):
        charity_id = request.charity_id
        listing_id = request.listing_id
        logger.info("VerifyCharity: charity_id=%s listing_id=%s", charity_id, listing_id)

        async with AsyncSessionLocal() as db:
            # OutSystems: registration + indemnity
            async with httpx.AsyncClient(timeout=5.0) as client:
                data = await _outsystems_get(client, f"/charities/{charity_id}")

            if data is None:
                logger.info("OutSystems unavailable — using demo mode for charity %s", charity_id)
            else:
                if data.get("status") != "ACTIVE_REGISTERED":
                    logger.warning("Charity %s not registered", charity_id)
                    return verification_pb2.VerifyResponse(valid=False, reason="NOT_REGISTERED")

                if data.get("indemnity_status", "UNSIGNED") != "SIGNED":
                    logger.warning("Charity %s has no signed indemnity", charity_id)
                    return verification_pb2.VerifyResponse(valid=False, reason="NO_INDEMNITY")

                logger.info("OutSystems: Charity %s legal OK", charity_id)

            # Local quota check
            result = await db.execute(
                select(func.count(CharityClaim.id)).where(
                    CharityClaim.charity_id == charity_id,
                    CharityClaim.created_at >= _today_start(),
                )
            )
            count = result.scalar()

            if count >= MAX_DAILY_CLAIMS:
                logger.warning("Charity %s exceeded daily limit (%s/%s)", charity_id, count, MAX_DAILY_CLAIMS)
                return verification_pb2.VerifyResponse(valid=False, reason="QUOTA_EXCEEDED")

            db.add(CharityClaim(charity_id=charity_id, listing_id=listing_id))
            await db.commit()

            logger.info("Charity %s approved (%s/%s today)", charity_id, count + 1, MAX_DAILY_CLAIMS)
            return verification_pb2.VerifyResponse(valid=True, reason="OK")

    # ── 2. Public user purchase verification ──────────────────────────────────
    async def VerifyPublicUser(self, request, _context):
        user_id    = request.user_id
        listing_id = request.listing_id
        logger.info("VerifyPublicUser: user_id=%s listing_id=%s", user_id, listing_id)

        async with AsyncSessionLocal() as db:
            # OutSystems: consumer indemnity acceptance
            async with httpx.AsyncClient(timeout=5.0) as client:
                data = await _outsystems_get(client, f"/users/{user_id}")

            if data is None:
                logger.info("OutSystems unavailable — using demo mode for user %s", user_id)
            else:
                if data.get("indemnity_status", "UNSIGNED") != "SIGNED":
                    logger.warning("User %s has not accepted consumer indemnity terms", user_id)
                    return verification_pb2.VerifyResponse(valid=False, reason="NO_CONSUMER_INDEMNITY")

                logger.info("OutSystems: User %s indemnity OK", user_id)

            # Local anti-scalping quota check
            result = await db.execute(
                select(func.count(PublicUserPurchase.id)).where(
                    PublicUserPurchase.user_id == user_id,
                    PublicUserPurchase.created_at >= _today_start(),
                )
            )
            count = result.scalar()

            if count >= MAX_DAILY_PURCHASES:
                logger.warning("User %s exceeded daily purchase limit (%s/%s)", user_id, count, MAX_DAILY_PURCHASES)
                return verification_pb2.VerifyResponse(valid=False, reason="PURCHASE_QUOTA_EXCEEDED")

            db.add(PublicUserPurchase(user_id=user_id, listing_id=listing_id))
            await db.commit()

            logger.info("User %s approved (%s/%s purchases today)", user_id, count + 1, MAX_DAILY_PURCHASES)
            return verification_pb2.VerifyResponse(valid=True, reason="OK")

    # ── 3. Vendor NEA compliance check ────────────────────────────────────────
    async def CheckVendorCompliance(self, request, _context):
        vendor_id = request.vendor_id
        logger.info("CheckVendorCompliance: vendor_id=%s", vendor_id)

        async with httpx.AsyncClient(timeout=5.0) as client:
            data = await _outsystems_get(client, f"/vendors/{vendor_id}")

        if data is None:
            logger.info("OutSystems unavailable — using demo mode for vendor %s", vendor_id)
            return verification_pb2.VerifyResponse(valid=True, reason="OK")

        nea_status = data.get("nea_license_status", "UNKNOWN")
        if nea_status != "ACTIVE":
            logger.warning("Vendor %s NEA license is %s", vendor_id, nea_status)
            reason = "NEA_LICENSE_EXPIRED" if nea_status == "EXPIRED" else "NEA_LICENSE_INVALID"
            return verification_pb2.VerifyResponse(valid=False, reason=reason)

        logger.info("Vendor %s NEA license active", vendor_id)
        return verification_pb2.VerifyResponse(valid=True, reason="OK")


# ── Startup ───────────────────────────────────────────────────────────────────

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def serve():
    await init_db()
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    verification_pb2_grpc.add_VerificationServicer_to_server(VerificationService(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    await server.start()
    logger.info("Verification service started on port %s", GRPC_PORT)
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
