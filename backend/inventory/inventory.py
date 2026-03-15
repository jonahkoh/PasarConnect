from contextlib import asynccontextmanager
from typing import List
from fastapi import Depends, FastAPI, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import geohash2

import database
from database import Base, get_db
from grpc_server import start_grpc_server
from models import FoodListing, ListingStatus
from schemas import FoodListingCreate, FoodListingUpdate, FoodListingResponse

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
    
    # Calculate geohash if location is provided (use precision 6 for better search matching)
    if new_listing.latitude is not None and new_listing.longitude is not None:
        new_listing.geohash = geohash2.encode(new_listing.latitude, new_listing.longitude, precision=6)
    
    db.add(new_listing)
    await db.commit()
    await db.refresh(new_listing)
    return new_listing


@app.put("/listings/{listing_id}", response_model=FoodListingResponse)
async def update_listing(
    listing_id: int = Path(..., gt=0),
    payload: FoodListingUpdate = None,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(FoodListing).where(FoodListing.id == listing_id))
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found.")
    
    # Update only provided fields
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(listing, field, value)
    
    # Recalculate geohash if location was updated
    if listing.latitude is not None and listing.longitude is not None:
        listing.geohash = geohash2.encode(listing.latitude, listing.longitude, precision=9)
    
    listing.version += 1
    await db.commit()
    await db.refresh(listing)
    return listing


@app.delete("/listings/{listing_id}", status_code=204)
async def delete_listing(
    listing_id: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(FoodListing).where(FoodListing.id == listing_id))
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found.")
    
    await db.delete(listing)
    await db.commit()


@app.get("/listings/search/nearby", response_model=List[FoodListingResponse])
async def search_nearby_listings(
    latitude: float = Query(..., ge=-90, le=90, description="Latitude of search center"),
    longitude: float = Query(..., ge=-180, le=180, description="Longitude of search center"),
    radius_km: float = Query(5.0, ge=0.1, le=100, description="Search radius in kilometers"),
    db: AsyncSession = Depends(get_db),
):
    """
    Search for listings near a geographic location using geohashing.
    Works for any location worldwide.
    
    Recommended radiuses:
    - 0.5 km: Very local search (same street/block)
    - 1 km: Neighborhood search
    - 2 km: District search
    - 5 km: Regional search (default)
    - 10+ km: Larger area search
    """
    # Calculate geohash precision based on radius
    # Higher radius = lower precision = larger area
    if radius_km >= 10:
        precision = 5  # ~4.8 km
    elif radius_km >= 5:
        precision = 6  # ~1.2 km
    elif radius_km >= 2:
        precision = 7  # ~150 m
    elif radius_km >= 0.5:
        precision = 8  # ~20 m
    else:
        precision = 9  # ~2.4 m
    
    center_geohash = geohash2.encode(latitude, longitude, precision=precision)
    
    # Generate nearby geohashes (9-box: center + 8 neighbors)
    try:
        nearby_geohashes = geohash2.neighbors(center_geohash)
        nearby_geohashes.add(center_geohash)
        nearby_geohashes_list = list(nearby_geohashes)
    except Exception:
        # Fallback: just use center geohash if neighbors fail
        nearby_geohashes_list = [center_geohash]
    
    # Query listings with matching geohashes
    result = await db.execute(
        select(FoodListing)
        .where(FoodListing.geohash.in_(nearby_geohashes_list))
        .where(FoodListing.status == ListingStatus.AVAILABLE)
        .order_by(FoodListing.created_at.desc())
    )
    
    return result.scalars().all()

