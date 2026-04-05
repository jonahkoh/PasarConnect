from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Path, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
import geohash2

import database
from database import Base, get_db
from grpc_server import start_grpc_server
from models import FoodListing, ListingStatus
from schemas import FoodListingCreate, FoodListingUpdate, FoodListingResponse

# Geohash precision used for storing and querying listing locations.
# Precision 6 ≈ 1.2 km cell size — matches the default 5 km search radius.
GEOHASH_STORE_PRECISION = 6


def _geohash_neighbors(geohash_str: str) -> set:
    """Return the 8 geohash cells surrounding *geohash_str* at the same precision.

    geohash2 v1.1 exposes only encode/decode/decode_exactly — no neighbors().
    We compute cells manually: shift ±2*half_width along each axis and re-encode.
    """
    precision = len(geohash_str)
    lat, lon, lat_err, lon_err = geohash2.decode_exactly(geohash_str)
    neighbors: set = set()
    for dlat in (-1, 0, 1):
        for dlon in (-1, 0, 1):
            if dlat == 0 and dlon == 0:
                continue  # skip center
            nlat = max(-90.0, min(90.0, lat + dlat * 2 * lat_err))
            nlon = ((lon + dlon * 2 * lon_err) + 180) % 360 - 180
            neighbors.add(geohash2.encode(nlat, nlon, precision=precision))
    return neighbors


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables on startup
    async with database.engine.begin() as conn:
        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'listing_status_enum') THEN
                        ALTER TYPE listing_status_enum ADD VALUE IF NOT EXISTS 'SOLD_PENDING_COLLECTION';
                    END IF;

                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'food_listings' AND column_name = 'expiry_date'
                    ) THEN
                        ALTER TABLE food_listings RENAME COLUMN expiry_date TO expiry;
                    END IF;
                END
                $$;
                """
            )
        )
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
    # All listings are stored at GEOHASH_STORE_PRECISION (6, ~1.2 km cell).
    # Searching must use the same precision — mixing precisions means the stored
    # hash "w21z7h" would never match a precision-8 search hash "w21z7hxx".
    # The 9-box at precision 6 covers ~3.6 × 2.4 km, sufficient for Singapore.
    # For radius > 25 km we expand to a 5×5 box to avoid missing border listings.
    precision = GEOHASH_STORE_PRECISION  # always 6

    center_geohash = geohash2.encode(latitude, longitude, precision=precision)

    # 9-box (3×3) covers ~3.6 × 2.4 km; expand to 5×5 for large radii
    if radius_km > 25:
        # Two rings out: neighbors-of-neighbors (adds 16 more cells)
        ring1 = _geohash_neighbors(center_geohash)
        ring2: set[str] = set()
        for h in ring1:
            ring2.update(_geohash_neighbors(h))
        nearby_geohashes = ring1 | ring2 | {center_geohash}
    else:
        nearby_geohashes = _geohash_neighbors(center_geohash)
        nearby_geohashes.add(center_geohash)

    nearby_geohashes_list = list(nearby_geohashes)

    # Query listings with matching geohashes
    result = await db.execute(
        select(FoodListing)
        .where(FoodListing.geohash.in_(nearby_geohashes_list))
        .where(FoodListing.status == ListingStatus.AVAILABLE)
        .order_by(FoodListing.created_at.desc())
    )

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

    # Calculate geohash if location is provided
    if new_listing.latitude is not None and new_listing.longitude is not None:
        new_listing.geohash = geohash2.encode(new_listing.latitude, new_listing.longitude, precision=GEOHASH_STORE_PRECISION)

    db.add(new_listing)
    await db.commit()
    await db.refresh(new_listing)
    return new_listing


@app.put("/listings/{listing_id}", response_model=FoodListingResponse)
async def update_listing(
    listing_id: int = Path(..., gt=0),
    payload: FoodListingUpdate = FoodListingUpdate(),
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
        listing.geohash = geohash2.encode(listing.latitude, listing.longitude, precision=GEOHASH_STORE_PRECISION)

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

