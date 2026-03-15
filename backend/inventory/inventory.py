from contextlib import asynccontextmanager
import math
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Path, Query
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


app = FastAPI(title="PasarConnect — Inventory Service", lifespan=lifespan)

EARTH_RADIUS_KM = 6371.0


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "inventory"}


@app.get("/listings/search/nearby", response_model=List[FoodListingResponse])
async def search_nearby_listings(
    latitude: float = Query(..., ge=-90, le=90, description="Center point latitude"),
    longitude: float = Query(..., ge=-180, le=180, description="Center point longitude"),
    radius_km: float = Query(..., gt=0, description="Search radius in kilometers"),
    db: AsyncSession = Depends(get_db),
):
    # Bounding box pre-filter to reduce rows loaded from the database.
    # 1 degree of latitude ≈ 111 km; longitude degrees vary by latitude.
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(latitude)) + 1e-10)

    result = await db.execute(
        select(FoodListing).where(
            FoodListing.latitude.isnot(None),
            FoodListing.longitude.isnot(None),
            FoodListing.latitude >= latitude - lat_delta,
            FoodListing.latitude <= latitude + lat_delta,
            FoodListing.longitude >= longitude - lon_delta,
            FoodListing.longitude <= longitude + lon_delta,
        )
    )
    listings = result.scalars().all()

    nearby = []
    for listing in listings:
        distance_km = _haversine_km(latitude, longitude, listing.latitude, listing.longitude)
        if distance_km <= radius_km:
            nearby.append(listing)

    return nearby


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in kilometres between two points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


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
