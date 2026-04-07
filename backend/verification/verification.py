"""
Verification Service — FastAPI application entry point.

Responsibilities:
  • Run DB schema migration (CREATE TABLE IF NOT EXISTS) on startup.
  • Start the async gRPC server inside the FastAPI lifespan.
  • Expose GET /health for the docker-compose health check.

Auth (login / JWT provisioning) is handled by the OutSystems service — not here.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import func, select

from database import AsyncSessionLocal
from database import init_db
from grpc_server import start_grpc_server
from models import PublicUserLateCancel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GRPC_PORT = int(os.getenv("VERIFICATION_GRPC_PORT", "50052"))


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initialising Verification DB schema...")
    await init_db()

    logger.info("Starting Verification gRPC server on port %s", GRPC_PORT)
    grpc_server = await start_grpc_server(port=GRPC_PORT)

    yield

    logger.info("Stopping Verification gRPC server...")
    await grpc_server.stop(grace=5)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PasarConnect — Verification Service",
    description="Quota (anti-hoarding) and no-show pattern checks via gRPC. No OutSystems calls.",
    lifespan=lifespan,
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "verification"}


class LateCancelBody(BaseModel):
    user_id:        int
    transaction_id: str


@app.post("/user-late-cancel", status_code=201)
async def record_user_late_cancel(body: LateCancelBody):
    """
    Called by the Payment Service (best-effort) when a user attempts to cancel
    after the cancellation window has expired.  Records it for admin review.
    """
    async with AsyncSessionLocal() as db:
        db.add(PublicUserLateCancel(
            user_id=body.user_id,
            transaction_id=body.transaction_id,
        ))
        await db.flush()
        result = await db.execute(
            select(func.count(PublicUserLateCancel.id)).where(
                PublicUserLateCancel.user_id == body.user_id
            )
        )
        total = result.scalar()
        await db.commit()

    return {"recorded": True, "total_late_cancels": total}

