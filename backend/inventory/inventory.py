from contextlib import asynccontextmanager
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import database
from database import Base, get_db
from grpc_server import start_grpc_server
from models import FoodListing
from schemas import FoodListingCreate, FoodListingResponse

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables on startup
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start the gRPC server alongside the HTTP server (same process, same event loop)
    grpc_server = await start_grpc_server()

    yield

    # Graceful shutdown: wait up to 5 s for in-flight RPCs to complete
    await grpc_server.stop(grace=5)
    await database.engine.dispose()


app = FastAPI(title="Foodloop — Inventory Service", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "inventory"}


@app.get("/listings", response_model=List[FoodListingResponse])
async def get_all_listings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FoodListing).order_by(FoodListing.created_at.desc()))
    return result.scalars().all()


@app.get("/listings/{listing_id}", response_model=FoodListingResponse)
async def get_listing(
    listing_id: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(FoodListing).where(FoodListing.id == listing_id))
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found.")
    return listing


@app.post("/listings", response_model=FoodListingResponse, status_code=201)
async def create_listing(
    payload: FoodListingCreate,
    db: AsyncSession = Depends(get_db),
):
    new_listing = FoodListing(**payload.model_dump())
    db.add(new_listing)
    await db.commit()
    await db.refresh(new_listing)
    return new_listing
