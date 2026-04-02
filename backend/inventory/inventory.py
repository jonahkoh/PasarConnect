from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException, Path, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
import geohash2

import database
from database import Base, get_db
from geocoding import GeocodingError, geocode_address
from grpc_server import start_grpc_server
from models import FoodListing, ListingStatus
from schemas import (
    FoodListingCreate,
    FoodListingUpdate,
    FoodListingResponse,
    FoodLocationResponse,
)


DEMO_LISTINGS = [
    {
        "vendor_id": "demo_vendor_tiong_bahru",
        "title": "Leafy Greens Bundle",
        "description": "Demo listing for live map testing near Tiong Bahru Market.",
        "quantity": 12,
        "address": "30 Seng Poh Rd, Singapore 168898",
        "latitude": 1.2849,
        "longitude": 103.8320,
    },
    {
        "vendor_id": "demo_vendor_tekka",
        "title": "Mixed Fruit Crate",
        "description": "Demo listing for live map testing near Tekka Centre.",
        "quantity": 6,
        "address": "665 Buffalo Rd, Singapore 210665",
        "latitude": 1.3061,
        "longitude": 103.8506,
    },
    {
        "vendor_id": "demo_vendor_geylang_serai",
        "title": "Tofu and Soy Pack",
        "description": "Demo listing for live map testing near Geylang Serai Market.",
        "quantity": 10,
        "address": "1 Geylang Serai, Singapore 402001",
        "latitude": 1.3174,
        "longitude": 103.8987,
    },
]


async def _seed_demo_listings() -> None:
    async with database.SessionLocal() as session:
        existing_listing = await session.scalar(select(FoodListing.id).limit(1))
        if existing_listing is not None:
            return

        expiry_date = datetime.now(timezone.utc) + timedelta(days=7)
        demo_rows = []

        for demo_listing in DEMO_LISTINGS:
            latitude = demo_listing["latitude"]
            longitude = demo_listing["longitude"]
            demo_rows.append(
                FoodListing(
                    vendor_id=demo_listing["vendor_id"],
                    title=demo_listing["title"],
                    description=demo_listing["description"],
                    quantity=demo_listing["quantity"],
                    expiry_date=expiry_date,
                    address=demo_listing["address"],
                    latitude=latitude,
                    longitude=longitude,
                    geohash=geohash2.encode(latitude, longitude, precision=6),
                    status=ListingStatus.AVAILABLE,
                )
            )

        session.add_all(demo_rows)
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables on startup
    async with database.engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            await conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'listing_status_enum') THEN
                            ALTER TYPE listing_status_enum ADD VALUE IF NOT EXISTS 'SOLD_PENDING_COLLECTION';
                        END IF;
                    END
                    $$;
                    """
                )
            )
        await conn.run_sync(Base.metadata.create_all)

    await _seed_demo_listings()

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


def _get_search_precision(radius_km: float) -> int:
    # Higher radius = lower precision = larger area
    if radius_km >= 10:
        return 5  # ~4.8 km
    if radius_km >= 5:
        return 6  # ~1.2 km
    if radius_km >= 2:
        return 7  # ~150 m
    if radius_km >= 0.5:
        return 8  # ~20 m
    return 9  # ~2.4 m


def _get_nearby_geohashes(latitude: float, longitude: float, radius_km: float) -> List[str]:
    precision = _get_search_precision(radius_km)
    center_geohash = geohash2.encode(latitude, longitude, precision=precision)

    try:
        nearby_geohashes = geohash2.neighbors(center_geohash)
        nearby_geohashes.add(center_geohash)
        return list(nearby_geohashes)
    except Exception:
        return [center_geohash]


@app.get("/listings", response_model=List[FoodListingResponse])
async def get_all_listings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FoodListing).order_by(FoodListing.created_at.desc()))
    return result.scalars().all()


@app.get("/listings/map/live", response_model=List[FoodLocationResponse])
async def get_live_map_listings(
    latitude: Optional[float] = Query(
        None, ge=-90, le=90, description="Optional user latitude for nearby live map markers"
    ),
    longitude: Optional[float] = Query(
        None, ge=-180, le=180, description="Optional user longitude for nearby live map markers"
    ),
    radius_km: float = Query(
        5.0, ge=0.1, le=100, description="Nearby search radius when coordinates are provided"
    ),
    db: AsyncSession = Depends(get_db),
):
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=422,
            detail="latitude and longitude must be provided together for nearby live map results.",
        )

    query = (
        select(FoodListing)
        .where(FoodListing.status == ListingStatus.AVAILABLE)
        .where(FoodListing.latitude.is_not(None))
        .where(FoodListing.longitude.is_not(None))
        .where(FoodListing.geohash.is_not(None))
        .order_by(FoodListing.created_at.desc())
    )

    if latitude is not None and longitude is not None:
        query = query.where(
            FoodListing.geohash.in_(_get_nearby_geohashes(latitude, longitude, radius_km))
        )

    result = await db.execute(query)
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

    if payload.address:
        try:
            lat, lng = await geocode_address(payload.address)
            new_listing.latitude = lat
            new_listing.longitude = lng
            new_listing.geohash = geohash2.encode(lat, lng, precision=6)
        except GeocodingError as e:
            raise HTTPException(status_code=422, detail=str(e))

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

    # Re-geocode if address was updated
    if payload.address:
        try:
            lat, lng = await geocode_address(payload.address)
            listing.latitude = lat
            listing.longitude = lng
            listing.geohash = geohash2.encode(lat, lng, precision=6)
        except GeocodingError as e:
            raise HTTPException(status_code=422, detail=str(e))
    
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
    nearby_geohashes_list = _get_nearby_geohashes(latitude, longitude, radius_km)

    # Query listings with matching geohashes
    result = await db.execute(
        select(FoodListing)
        .where(FoodListing.geohash.in_(nearby_geohashes_list))
        .where(FoodListing.status == ListingStatus.AVAILABLE)
        .order_by(FoodListing.created_at.desc())
    )
    
    return result.scalars().all()

