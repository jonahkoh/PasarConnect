import grpc
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import inventory_client
import publisher
from database import engine, Base, get_db
from models import Claim
from schemas import ClaimCreate, ClaimResponse


# ── App lifespan: create DB tables on startup ────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Claim Service", lifespan=lifespan)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "claim"}


@app.post("/claims", response_model=ClaimResponse, status_code=201)
async def create_claim(body: ClaimCreate, db: AsyncSession = Depends(get_db)):
    # 1. Lock the listing in Inventory via gRPC
    try:
        new_version = await inventory_client.lock_listing_pending_collection(
            listing_id       = body.listing_id,
            expected_version = body.listing_version,
        )
    except grpc.aio.AioRpcError as exc:
        code = exc.code()
        if code == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Listing not found")
        if code == grpc.StatusCode.ABORTED:
            raise HTTPException(status_code=409, detail="Listing already claimed — please refresh")
        raise HTTPException(status_code=503, detail="Inventory service unavailable")

    # TODO (Phase 1 Step 3): call Verification Service here

    # 2. Persist the claim
    claim = Claim(
        listing_id      = body.listing_id,
        charity_id      = body.charity_id,
        listing_version = new_version,
    )
    db.add(claim)
    await db.commit()
    await db.refresh(claim)

    # 3. Publish event (best-effort — non-fatal if RabbitMQ is down)
    publisher.publish_claim_success(claim.id, claim.listing_id, claim.charity_id)

    return claim
