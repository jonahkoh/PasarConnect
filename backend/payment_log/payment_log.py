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
from sqlalchemy import text

from database import Base, engine


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
