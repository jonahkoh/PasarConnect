"""
Payment Log Service — State Manager.

Owns the PostgreSQL database.  Exposes three internal REST endpoints
consumed only by the Payment Orchestrator:

  POST  /logs                       — create a new PENDING record
  GET   /logs/{transaction_id}      — fetch a record (idempotency check)
  PATCH /logs/{transaction_id}      — update status (SUCCESS / REFUNDED / FAILED)

No external client ever calls this service directly.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import database
from database import Base, engine, get_db
from models import PaymentRecord, PaymentStatus
from schemas import LogCreate, LogResponse, LogUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables on startup
    async with engine.begin() as conn:
        # Backward-compatible enum migration for existing Docker volumes.
        # Older DBs may have paymentstatus enum without COLLECTED.
        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'paymentstatus') THEN
                        ALTER TYPE paymentstatus ADD VALUE IF NOT EXISTS 'COLLECTED';
                    END IF;
                END
                $$;
                """
            )
        )
        await conn.run_sync(Base.metadata.create_all)

    # Run gRPC server in-process for orchestrator status updates.
    from grpc_server import start_grpc_server
    grpc_server = await start_grpc_server()

    yield

    await grpc_server.stop(grace=5)
    await engine.dispose()


app = FastAPI(title="PasarConnect — Payment Log Service", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "payment-log"}


# ── POST /logs ────────────────────────────────────────────────────────────────

@app.post("/logs", response_model=LogResponse, status_code=201)
async def create_log(payload: LogCreate, db: AsyncSession = Depends(get_db)):
    """
    Called by the Orchestrator immediately after a Stripe PaymentIntent is created.
    Persists the record with status=PENDING so retries can detect it.
    Returns 409 if the stripe_transaction_id already exists (duplicate intent call).
    """
    # Guard against duplicate creation (should not happen in normal flow, but be safe).
    existing = await db.scalar(
        select(PaymentRecord).where(
            PaymentRecord.stripe_transaction_id == payload.stripe_transaction_id
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Log for transaction {payload.stripe_transaction_id!r} already exists.",
        )

    record = PaymentRecord(
        stripe_transaction_id = payload.stripe_transaction_id,
        listing_id            = payload.listing_id,
        listing_version       = payload.listing_version,
        amount                = payload.amount,
        status                = PaymentStatus.PENDING,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


# ── GET /logs/{transaction_id} ────────────────────────────────────────────────

@app.get("/logs/{transaction_id}", response_model=LogResponse)
async def get_log(transaction_id: str, db: AsyncSession = Depends(get_db)):
    """
    Called by the Orchestrator's idempotency check before processing a webhook.
    Returns 404 if no record exists — the Orchestrator treats this as a signal
    to retry later (race between intent creation and webhook arrival).
    """
    record = await db.scalar(
        select(PaymentRecord).where(
            PaymentRecord.stripe_transaction_id == transaction_id
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"No log for transaction {transaction_id!r}.")
    return record


# ── PATCH /logs/{transaction_id} ──────────────────────────────────────────────

@app.patch("/logs/{transaction_id}", response_model=LogResponse)
async def update_log(
    transaction_id: str,
    payload: LogUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Called by the Orchestrator to advance a record's status.
    PENDING  → SUCCESS   (gRPC hard-lock succeeded)
    PENDING  → REFUNDED  (compensating transaction executed successfully)
    PENDING  → FAILED    (both gRPC and Stripe refund failed — ops alert needed)
    """
    record = await db.scalar(
        select(PaymentRecord).where(
            PaymentRecord.stripe_transaction_id == transaction_id
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"No log for transaction {transaction_id!r}.")

    record.status = payload.status
    await db.commit()
    await db.refresh(record)
    return record
