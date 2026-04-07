"""
Payment Log Service — State Manager.

Owns the PostgreSQL database and exposes gRPC APIs consumed by the
Payment Orchestrator:

    CreatePaymentLog(...)   — create a PENDING record after intent creation
    GetPaymentLog(...)      — read record for idempotency and validation
    UpdatePaymentStatus(...)— transition status and sync listing_version

No external client ever calls this service directly.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select, text

from database import Base, SessionLocal, engine
from models import PaymentRecord


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
                        ALTER TYPE paymentstatus ADD VALUE IF NOT EXISTS 'FORFEITED';
                    END IF;
                END
                $$;
                """
            )
        )
        await conn.run_sync(Base.metadata.create_all)
        # Backward-compatible column migration for existing Docker volumes.
        # Adds user_id to payment_records if it doesn't already exist.
        await conn.execute(
            text(
                "ALTER TABLE payment_records "
                "ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 0;"
            )
        )

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


@app.get("/user-history/{user_id}")
async def get_user_history(user_id: int):
    """
    Internal endpoint — called by Payment Service to fetch a user's purchase history.
    Returns records ordered newest-first.
    """
    async with SessionLocal() as db:
        result = await db.execute(
            select(PaymentRecord)
            .where(PaymentRecord.user_id == user_id)
            .order_by(PaymentRecord.created_at.desc())
        )
        records = result.scalars().all()

    return [
        {
            "transaction_id": r.stripe_transaction_id,
            "listing_id":     r.listing_id,
            "amount":         r.amount,
            "status":         r.status.value,
            "created_at":     r.created_at.isoformat() if r.created_at else None,
            "updated_at":     r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in records
    ]
