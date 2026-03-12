"""
Claim Log Service — State Manager.

Owns the Claim database and exposes internal CRUD endpoints used by the
Claim Orchestrator and frontend history views.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, engine
from models import Base, ClaimRecord
from schemas import LogCreate, LogResponse, LogUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
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


@app.patch("/logs/{claim_id}", response_model=LogResponse)
async def update_log_status(claim_id: int, payload: LogUpdate, db: AsyncSession = Depends(get_db)):
    record = await db.get(ClaimRecord, claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Claim log {claim_id} not found")

    record.status = payload.status
    await db.commit()
    await db.refresh(record)
    return record
