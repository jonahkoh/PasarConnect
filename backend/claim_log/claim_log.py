"""
Claim Log Service — State Manager.

Owns the Claim database and exposes internal CRUD endpoints used by the
Claim Orchestrator and frontend history views.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, engine
from models import Base, ClaimRecord, ClaimStatus
from schemas import LogCreate, LogResponse, LogUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        # Backward-compatible enum migration for existing Docker volumes.
        # Older DBs may have claimstatus enum without AWAITING_VENDOR_APPROVAL.
        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'claimstatus') THEN
                        ALTER TYPE claimstatus ADD VALUE IF NOT EXISTS 'AWAITING_VENDOR_APPROVAL';
                    END IF;
                END
                $$;
                """
            )
        )
        await conn.run_sync(Base.metadata.create_all)

    # Run gRPC server in-process so orchestrator can update claim state via RPC.
    from grpc_server import start_grpc_server
    grpc_server = await start_grpc_server()

    yield

    await grpc_server.stop(grace=5)
    await engine.dispose()


app = FastAPI(title="PasarConnect — Claim Log Service", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "claim-log"}


@app.post("/logs", response_model=LogResponse, status_code=201)
async def create_log(payload: LogCreate, db: AsyncSession = Depends(get_db)):
    record = ClaimRecord(
        listing_id=payload.listing_id,
        charity_id=payload.charity_id,
        listing_version=payload.listing_version,
        status=payload.status,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@app.get("/logs/{charity_id}", response_model=list[LogResponse])
async def get_logs_by_charity(charity_id: int, db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(ClaimRecord)
        .where(ClaimRecord.charity_id == charity_id)
        .order_by(ClaimRecord.created_at.desc())
    )
    return list(rows)


@app.get("/logs/listing/{listing_id}/active", response_model=LogResponse)
async def get_active_claim_for_listing(listing_id: int, db: AsyncSession = Depends(get_db)):
    """Return the most recent PENDING_COLLECTION or AWAITING_VENDOR_APPROVAL claim for a listing."""
    row = await db.scalar(
        select(ClaimRecord)
        .where(ClaimRecord.listing_id == listing_id)
        .where(ClaimRecord.status.in_([ClaimStatus.PENDING_COLLECTION, ClaimStatus.AWAITING_VENDOR_APPROVAL]))
        .order_by(ClaimRecord.created_at.desc())
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"No active claim for listing {listing_id}")
    return row


@app.patch("/logs/{claim_id}", response_model=LogResponse)
async def update_log_status(claim_id: int, payload: LogUpdate, db: AsyncSession = Depends(get_db)):
    record = await db.get(ClaimRecord, claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Claim log {claim_id} not found")

    # Idempotent update: no-op if caller repeats the same status.
    if record.status == payload.status:
        return record

    record.status = payload.status
    await db.commit()
    await db.refresh(record)
    return record
