"""
Inventory Service tests — HTTP layer + optimistic locking (14 tests).
Uses in-memory SQLite so no real DB is needed.
The sys.path is managed by backend/conftest.py before each test.
"""
import sys, os

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

SQLITE_URL  = "sqlite+aiosqlite:///:memory:"
FUTURE_DATE = "2099-12-31T00:00:00Z"
PAST_DATE   = "2000-01-01T00:00:00Z"
FUTURE_DT   = datetime(2099, 12, 31, tzinfo=timezone.utc)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def http_db():
    """
    Spins up an in-memory SQLite DB, patches inventory's database.engine so that
    FastAPI's lifespan and get_db both use SQLite instead of Postgres.
    """
    import database
    from inventory import app
    from models import Base

    test_engine  = create_async_engine(SQLITE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession  = async_sessionmaker(test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with TestSession() as session:
            yield session

    with patch.object(database, "engine", test_engine):
        from inventory import get_db
        app.dependency_overrides[get_db] = override_get_db
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
        app.dependency_overrides.clear()

    await test_engine.dispose()


@pytest_asyncio.fixture()
async def lock_db():
    """Bare SQLite session for testing lock_service directly."""
    from models import Base

    engine  = create_async_engine(SQLITE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        yield session
    await engine.dispose()


# ── HTTP tests ────────────────────────────────────────────────────────────────

async def test_health(http_db):
    r = await http_db.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


async def test_get_listings_empty(http_db):
    r = await http_db.get("/listings")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_listing(http_db):
    payload = {
        "vendor_id": "vendor_1",
        "title": "Bread",
        "description": "Day-old sourdough",
        "quantity": 5,
        "expiry_date": FUTURE_DATE,
    }
    r = await http_db.post("/listings", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["title"]    == "Bread"
    assert data["quantity"] == 5
    assert data["status"]   == "AVAILABLE"
    assert data["version"]  == 0


async def test_get_listing_by_id(http_db):
    payload = {"vendor_id": "vendor_1", "title": "Apple", "description": "Fresh", "quantity": 3, "expiry_date": FUTURE_DATE}
    created = (await http_db.post("/listings", json=payload)).json()
    r = await http_db.get(f"/listings/{created['id']}")
    assert r.status_code == 200
    assert r.json()["title"] == "Apple"


async def test_get_listing_not_found(http_db):
    r = await http_db.get("/listings/999")
    assert r.status_code == 404


async def test_create_listing_zero_quantity(http_db):
    payload = {"vendor_id": "vendor_1", "title": "X", "description": "Y", "quantity": 0, "expiry_date": FUTURE_DATE}
    r = await http_db.post("/listings", json=payload)
    assert r.status_code == 422


async def test_create_listing_past_expiry(http_db):
    payload = {"vendor_id": "vendor_1", "title": "Stale", "description": "Old", "quantity": 1, "expiry_date": PAST_DATE}
    r = await http_db.post("/listings", json=payload)
    assert r.status_code == 422


# ── Optimistic locking tests ───────────────────────────────────────────────────
# version starts at 0 (server_default) so the first lock uses expected_version=0

async def test_lock_success(lock_db):
    from lock_service import lock_listing
    from models import FoodListing, ListingStatus

    listing = FoodListing(vendor_id="v1", title="T", description="D", quantity=1, expiry_date=FUTURE_DT)
    lock_db.add(listing)
    await lock_db.commit()
    await lock_db.refresh(listing)

    new_version = await lock_listing(lock_db, listing.id, expected_version=0, new_status=ListingStatus.PENDING_COLLECTION)
    assert new_version == 1


async def test_lock_conflict(lock_db):
    from lock_service import lock_listing, LockConflictError
    from models import FoodListing, ListingStatus

    listing = FoodListing(vendor_id="v1", title="T", description="D", quantity=1, expiry_date=FUTURE_DT)
    lock_db.add(listing)
    await lock_db.commit()
    await lock_db.refresh(listing)

    with pytest.raises(LockConflictError):
        await lock_listing(lock_db, listing.id, expected_version=99, new_status=ListingStatus.PENDING_COLLECTION)


async def test_lock_not_found(lock_db):
    from lock_service import lock_listing, ListingNotFoundError
    from models import ListingStatus

    with pytest.raises(ListingNotFoundError):
        await lock_listing(lock_db, 999, expected_version=0, new_status=ListingStatus.PENDING_COLLECTION)


async def test_sequential_locks(lock_db):
    from lock_service import lock_listing
    from models import FoodListing, ListingStatus

    listing = FoodListing(vendor_id="v1", title="T", description="D", quantity=1, expiry_date=FUTURE_DT)
    lock_db.add(listing)
    await lock_db.commit()
    await lock_db.refresh(listing)

    v1 = await lock_listing(lock_db, listing.id, 0, ListingStatus.PENDING_COLLECTION)
    assert v1 == 1
    v2 = await lock_listing(lock_db, listing.id, 1, ListingStatus.AVAILABLE)
    assert v2 == 2


async def test_stale_version_after_lock(lock_db):
    from lock_service import lock_listing, LockConflictError
    from models import FoodListing, ListingStatus

    listing = FoodListing(vendor_id="v1", title="T", description="D", quantity=1, expiry_date=FUTURE_DT)
    lock_db.add(listing)
    await lock_db.commit()
    await lock_db.refresh(listing)

    await lock_listing(lock_db, listing.id, 0, ListingStatus.PENDING_COLLECTION)
    with pytest.raises(LockConflictError):
        # version 0 is now stale; current is 1
        await lock_listing(lock_db, listing.id, 0, ListingStatus.AVAILABLE)


async def test_lock_to_sold(lock_db):
    from lock_service import lock_listing
    from models import FoodListing, ListingStatus

    listing = FoodListing(vendor_id="v1", title="T", description="D", quantity=1, expiry_date=FUTURE_DT)
    lock_db.add(listing)
    await lock_db.commit()
    await lock_db.refresh(listing)

    v1 = await lock_listing(lock_db, listing.id, 0, ListingStatus.PENDING_PAYMENT)
    v2 = await lock_listing(lock_db, listing.id, v1, ListingStatus.SOLD)
    assert v2 == 2


async def test_lock_rollback(lock_db):
    from lock_service import lock_listing
    from models import FoodListing, ListingStatus

    listing = FoodListing(vendor_id="v1", title="T", description="D", quantity=1, expiry_date=FUTURE_DT)
    lock_db.add(listing)
    await lock_db.commit()
    await lock_db.refresh(listing)

    v1 = await lock_listing(lock_db, listing.id, 0, ListingStatus.PENDING_PAYMENT)
    # Payment failed → rollback to AVAILABLE
    v2 = await lock_listing(lock_db, listing.id, v1, ListingStatus.AVAILABLE)
    assert v2 == 2


# ── UPDATE tests ───────────────────────────────────────────────────────────────

SG_LAT = 1.3521
SG_LNG = 103.8198

def _listing_payload(**overrides):
    base = {
        "vendor_id": "vendor_1",
        "title": "Fresh Bread",
        "quantity": 5,
        "expiry_date": FUTURE_DATE,
    }
    base.update(overrides)
    return base


async def test_update_listing_title(http_db):
    created = (await http_db.post("/listings", json=_listing_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={"title": "Updated Bread"})
    assert r.status_code == 200
    assert r.json()["title"] == "Updated Bread"
    assert r.json()["quantity"] == created["quantity"]  # unchanged


async def test_update_listing_increments_version(http_db):
    created = (await http_db.post("/listings", json=_listing_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={"quantity": 10})
    assert r.json()["version"] == created["version"] + 1


async def test_update_listing_status(http_db):
    created = (await http_db.post("/listings", json=_listing_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={"status": "SOLD"})
    assert r.status_code == 200
    assert r.json()["status"] == "SOLD"


async def test_update_listing_location_recalculates_geohash(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        created = (await http_db.post("/listings", json=_listing_payload(address="Jurong West Street 61"))).json()
    old_geohash = created["geohash"]
    # Move to Tokyo — completely different geohash
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(35.6762, 139.6503))):
        r = await http_db.put(f"/listings/{created['id']}", json={"address": "Tokyo, Japan"})
    assert r.status_code == 200
    assert r.json()["geohash"] != old_geohash
    assert len(r.json()["geohash"]) == 6  # precision must stay at 6


async def test_update_listing_not_found(http_db):
    r = await http_db.put("/listings/99999", json={"title": "Ghost"})
    assert r.status_code == 404


async def test_update_listing_past_expiry_rejected(http_db):
    created = (await http_db.post("/listings", json=_listing_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={"expiry_date": PAST_DATE})
    assert r.status_code == 422


async def test_update_listing_invalid_quantity_rejected(http_db):
    created = (await http_db.post("/listings", json=_listing_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={"quantity": -1})
    assert r.status_code == 422


# ── DELETE tests ───────────────────────────────────────────────────────────────

async def test_delete_listing_success(http_db):
    created = (await http_db.post("/listings", json=_listing_payload())).json()
    r = await http_db.delete(f"/listings/{created['id']}")
    assert r.status_code == 204


async def test_delete_listing_no_longer_retrievable(http_db):
    created = (await http_db.post("/listings", json=_listing_payload())).json()
    await http_db.delete(f"/listings/{created['id']}")
    r = await http_db.get(f"/listings/{created['id']}")
    assert r.status_code == 404


async def test_delete_listing_not_found(http_db):
    r = await http_db.delete("/listings/99999")
    assert r.status_code == 404


async def test_delete_listing_removed_from_all_listings(http_db):
    created = (await http_db.post("/listings", json=_listing_payload())).json()
    await http_db.delete(f"/listings/{created['id']}")
    r = await http_db.get("/listings")
    assert r.json() == []


# ── Geohash / nearby search tests ─────────────────────────────────────────────

async def test_create_listing_sets_geohash(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        r = await http_db.post("/listings", json=_listing_payload(address="Jurong West Street 61"))
    data = r.json()
    assert data["geohash"] is not None
    assert len(data["geohash"]) == 6  # precision 6


async def test_create_listing_without_location_no_geohash(http_db):
    r = await http_db.post("/listings", json=_listing_payload(address=None))
    assert r.status_code == 201
    assert r.json()["geohash"] is None


async def test_nearby_search_finds_close_listing(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        await http_db.post("/listings", json=_listing_payload(address="Jurong West Street 61"))
    # Search from the exact same point — must be in the 9-cell neighbourhood
    r = await http_db.get("/listings/search/nearby", params={
        "latitude": SG_LAT,
        "longitude": SG_LNG,
        "radius_km": 5,
    })
    assert r.status_code == 200
    assert len(r.json()) >= 1


async def test_nearby_search_excludes_far_listing(http_db):
    await http_db.post("/listings", json=_listing_payload(latitude=SG_LAT, longitude=SG_LNG))
    # Search from Tokyo — no geohash overlap with Singapore
    r = await http_db.get("/listings/search/nearby", params={
        "latitude": 35.6762,
        "longitude": 139.6503,
        "radius_km": 5,
    })
    assert r.status_code == 200
    assert len(r.json()) == 0


async def test_nearby_search_only_returns_available(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        r1 = (await http_db.post("/listings", json=_listing_payload(address="Jurong West Street 61"))).json()
        r2 = (await http_db.post("/listings", json=_listing_payload(title="Sold item", address="Jurong West Street 61"))).json()
    await http_db.put(f"/listings/{r2['id']}", json={"status": "SOLD"})

    r = await http_db.get("/listings/search/nearby", params={
        "latitude": SG_LAT, "longitude": SG_LNG, "radius_km": 5,
    })
    results = r.json()
    assert all(item["status"] == "AVAILABLE" for item in results)
    ids = [item["id"] for item in results]
    assert r1["id"] in ids
    assert r2["id"] not in ids


async def test_nearby_search_missing_params(http_db):
    r = await http_db.get("/listings/search/nearby", params={"latitude": SG_LAT})
    assert r.status_code == 422


async def test_nearby_search_invalid_coordinates(http_db):
    r = await http_db.get("/listings/search/nearby", params={
        "latitude": 999, "longitude": SG_LNG, "radius_km": 5,
    })
    assert r.status_code == 422


async def test_nearby_search_empty_db(http_db):
    r = await http_db.get("/listings/search/nearby", params={
        "latitude": SG_LAT, "longitude": SG_LNG, "radius_km": 5,
    })
    assert r.status_code == 200
    assert r.json() == []


async def test_geohash_precision_consistent_after_update(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        created = (await http_db.post("/listings", json=_listing_payload(address="Jurong West Street 61"))).json()
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(1.2900, 103.8500))):
        r = await http_db.put(f"/listings/{created['id']}", json={"address": "Queenstown, Singapore"})
    assert len(r.json()["geohash"]) == 6


async def test_live_map_returns_only_available_listings_with_coordinates(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        available = (await http_db.post("/listings", json=_listing_payload(address="Jurong West Street 61"))).json()
        sold = (await http_db.post("/listings", json=_listing_payload(title="Sold item", address="Jurong West Street 61"))).json()

    await http_db.put(f"/listings/{sold['id']}", json={"status": "SOLD"})
    await http_db.post("/listings", json=_listing_payload(title="No map pin"))

    r = await http_db.get("/listings/map/live")

    assert r.status_code == 200
    data = r.json()
    assert [item["id"] for item in data] == [available["id"]]
    assert data[0]["latitude"] == SG_LAT
    assert data[0]["longitude"] == SG_LNG
    assert data[0]["geohash"] == available["geohash"]


async def test_live_map_supports_nearby_filtering(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        near = (await http_db.post("/listings", json=_listing_payload(address="Jurong West Street 61"))).json()
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(35.6762, 139.6503))):
        far = (await http_db.post("/listings", json=_listing_payload(title="Tokyo item", address="Tokyo, Japan"))).json()

    r = await http_db.get("/listings/map/live", params={
        "latitude": SG_LAT,
        "longitude": SG_LNG,
        "radius_km": 5,
    })

    assert r.status_code == 200
    ids = [item["id"] for item in r.json()]
    assert near["id"] in ids
    assert far["id"] not in ids


async def test_live_map_rejects_partial_coordinates(http_db):
    r = await http_db.get("/listings/map/live", params={"latitude": SG_LAT})
    assert r.status_code == 422
