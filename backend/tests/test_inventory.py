"""
Inventory Service tests — HTTP layer + optimistic locking (57 tests).
Uses in-memory SQLite so no real DB is needed.
The sys.path is managed by backend/conftest.py before each test.
"""
import sys
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

SQLITE_URL  = "sqlite+aiosqlite:///:memory:"
FUTURE_DATE = "2099-12-31T00:00:00Z"
PAST_DATE   = "2000-01-01T00:00:00Z"
FUTURE_DT   = datetime(2099, 12, 31, tzinfo=timezone.utc)
SG_LAT      = 1.3521
SG_LNG      = 103.8198


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def http_db():
    # Protobuf gencode/runtime version mismatch prevents grpc_server from importing.
    # Mock it out — HTTP tests don't exercise gRPC at all.
    grpc_mock = MagicMock()
    grpc_mock.start_grpc_server = AsyncMock(return_value=MagicMock(stop=AsyncMock()))
    sys.modules.setdefault("grpc_server", grpc_mock)
    sys.modules.setdefault("inventory_pb2", MagicMock())
    sys.modules.setdefault("inventory_pb2_grpc", MagicMock())

    import database
    from inventory import app
    from models import Base

    test_engine = create_async_engine(SQLITE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)

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
    from models import Base

    engine  = create_async_engine(SQLITE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        yield session
    await engine.dispose()


def _payload(**overrides):
    """Base valid payload for POST /listings."""
    base = {
        "vendor_id": "vendor_001",
        "title": "Sourdough Bread",
        "description": "Day-old artisan loaf",
        "quantity": 5,
        "expiry_date": FUTURE_DATE,
    }
    base.update(overrides)
    return base


# ── GET /health ───────────────────────────────────────────────────────────────

async def test_health(http_db):
    r = await http_db.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy", "service": "inventory"}


# ── GET /listings ─────────────────────────────────────────────────────────────

async def test_get_listings_empty(http_db):
    r = await http_db.get("/listings")
    assert r.status_code == 200
    assert r.json() == []


async def test_get_listings_returns_all(http_db):
    await http_db.post("/listings", json=_payload(title="Item A"))
    await http_db.post("/listings", json=_payload(title="Item B"))
    r = await http_db.get("/listings")
    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_get_listings_ordered_by_created_desc(http_db):
    await http_db.post("/listings", json=_payload(title="First"))
    await http_db.post("/listings", json=_payload(title="Second"))
    items = (await http_db.get("/listings")).json()
    assert items[0]["title"] == "Second"
    assert items[1]["title"] == "First"


# ── GET /listings/{id} ────────────────────────────────────────────────────────

async def test_get_listing_by_id(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    r = await http_db.get(f"/listings/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


async def test_get_listing_not_found(http_db):
    r = await http_db.get("/listings/999")
    assert r.status_code == 404
    assert "999" in r.json()["detail"]


async def test_get_listing_id_zero_rejected(http_db):
    r = await http_db.get("/listings/0")
    assert r.status_code == 422


# ── POST /listings ────────────────────────────────────────────────────────────

async def test_create_listing(http_db):
    r = await http_db.post("/listings", json=_payload())
    assert r.status_code == 201
    data = r.json()
    assert data["title"]   == "Sourdough Bread"
    assert data["quantity"] == 5
    assert data["status"]  == "AVAILABLE"
    assert data["version"] == 0


async def test_create_listing_with_address_sets_location(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        r = await http_db.post("/listings", json=_payload(address="Jurong West Street 61"))
    assert r.status_code == 201
    data = r.json()
    assert data["latitude"]  == SG_LAT
    assert data["longitude"] == SG_LNG
    assert data["geohash"]   is not None
    assert len(data["geohash"]) == 6


async def test_create_listing_without_address_no_location(http_db):
    r = await http_db.post("/listings", json=_payload())
    assert r.status_code == 201
    data = r.json()
    assert data["latitude"]  is None
    assert data["longitude"] is None
    assert data["geohash"]   is None


async def test_create_listing_bad_address_returns_422(http_db):
    from geocoding import GeocodingError
    with patch("inventory.geocode_address", new=AsyncMock(side_effect=GeocodingError("not found"))):
        r = await http_db.post("/listings", json=_payload(address="Nonexistent Place XYZ"))
    assert r.status_code == 422


async def test_create_listing_zero_quantity_rejected(http_db):
    r = await http_db.post("/listings", json=_payload(quantity=0))
    assert r.status_code == 422


async def test_create_listing_negative_quantity_rejected(http_db):
    r = await http_db.post("/listings", json=_payload(quantity=-1))
    assert r.status_code == 422


async def test_create_listing_past_expiry_rejected(http_db):
    r = await http_db.post("/listings", json=_payload(expiry_date=PAST_DATE))
    assert r.status_code == 422


async def test_create_listing_missing_vendor_id_rejected(http_db):
    payload = _payload()
    del payload["vendor_id"]
    r = await http_db.post("/listings", json=payload)
    assert r.status_code == 422


async def test_create_listing_missing_title_rejected(http_db):
    payload = _payload()
    del payload["title"]
    r = await http_db.post("/listings", json=payload)
    assert r.status_code == 422


# ── PUT /listings/{id} ────────────────────────────────────────────────────────

async def test_update_listing_title(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={"title": "New Title"})
    assert r.status_code == 200
    data = r.json()
    assert data["title"]       == "New Title"
    assert data["description"] == created["description"]  # unchanged
    assert data["version"]     == 1


async def test_update_listing_quantity(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={"quantity": 99})
    assert r.status_code == 200
    assert r.json()["quantity"] == 99


async def test_update_listing_status(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={"status": "SOLD"})
    assert r.status_code == 200
    assert r.json()["status"] == "SOLD"


async def test_update_listing_increments_version(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    assert created["version"] == 0
    r1 = (await http_db.put(f"/listings/{created['id']}", json={"quantity": 2})).json()
    assert r1["version"] == 1
    r2 = (await http_db.put(f"/listings/{created['id']}", json={"quantity": 3})).json()
    assert r2["version"] == 2


async def test_update_listing_empty_body_no_version_bump(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={})
    assert r.status_code == 200
    assert r.json()["version"] == 0  # no bump on empty update


async def test_update_listing_address_re_geocodes(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    assert created["geohash"] is None

    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        r = await http_db.put(f"/listings/{created['id']}", json={"address": "Jurong West Street 61"})
    assert r.status_code == 200
    data = r.json()
    assert data["latitude"]  == SG_LAT
    assert data["longitude"] == SG_LNG
    assert data["geohash"]   is not None


async def test_update_listing_not_found(http_db):
    r = await http_db.put("/listings/999", json={"title": "Ghost"})
    assert r.status_code == 404


async def test_update_listing_past_expiry_rejected(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={"expiry_date": PAST_DATE})
    assert r.status_code == 422


async def test_update_listing_invalid_quantity_rejected(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    r = await http_db.put(f"/listings/{created['id']}", json={"quantity": 0})
    assert r.status_code == 422


# ── DELETE /listings/{id} ─────────────────────────────────────────────────────

async def test_delete_listing_returns_204(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    r = await http_db.delete(f"/listings/{created['id']}")
    assert r.status_code == 204


async def test_delete_listing_no_longer_retrievable(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    await http_db.delete(f"/listings/{created['id']}")
    r = await http_db.get(f"/listings/{created['id']}")
    assert r.status_code == 404


async def test_delete_listing_removed_from_all_listings(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    await http_db.delete(f"/listings/{created['id']}")
    ids = [item["id"] for item in (await http_db.get("/listings")).json()]
    assert created["id"] not in ids


async def test_delete_listing_not_found(http_db):
    r = await http_db.delete("/listings/999")
    assert r.status_code == 404


async def test_put_after_delete_returns_404(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    await http_db.delete(f"/listings/{created['id']}")
    r = await http_db.put(f"/listings/{created['id']}", json={"title": "Ghost"})
    assert r.status_code == 404


# ── GET /listings/search/nearby ───────────────────────────────────────────────

async def test_nearby_search_finds_listing_at_same_coords(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        created = (await http_db.post("/listings", json=_payload(address="Jurong West"))).json()
    r = await http_db.get("/listings/search/nearby", params={"latitude": SG_LAT, "longitude": SG_LNG, "radius_km": 5})
    assert r.status_code == 200
    assert created["id"] in [item["id"] for item in r.json()]


async def test_nearby_search_excludes_far_listing(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        await http_db.post("/listings", json=_payload(address="Singapore"))
    # Search from Tokyo
    r = await http_db.get("/listings/search/nearby", params={"latitude": 35.6762, "longitude": 139.6503, "radius_km": 5})
    assert r.status_code == 200
    assert len(r.json()) == 0


async def test_nearby_search_only_returns_available(http_db):
    with patch("inventory.geocode_address", new=AsyncMock(return_value=(SG_LAT, SG_LNG))):
        avail = (await http_db.post("/listings", json=_payload(address="A"))).json()
        sold  = (await http_db.post("/listings", json=_payload(title="Sold", address="B"))).json()
    await http_db.put(f"/listings/{sold['id']}", json={"status": "SOLD"})

    r = await http_db.get("/listings/search/nearby", params={"latitude": SG_LAT, "longitude": SG_LNG, "radius_km": 5})
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()]
    assert avail["id"] in ids
    assert sold["id"] not in ids
    assert all(item["status"] == "AVAILABLE" for item in r.json())


async def test_nearby_search_excludes_listing_without_geohash(http_db):
    created = (await http_db.post("/listings", json=_payload())).json()
    assert created["geohash"] is None
    r = await http_db.get("/listings/search/nearby", params={"latitude": SG_LAT, "longitude": SG_LNG, "radius_km": 100})
    ids = [item["id"] for item in r.json()]
    assert created["id"] not in ids


async def test_nearby_search_empty_area_returns_empty_list(http_db):
    r = await http_db.get("/listings/search/nearby", params={"latitude": 30.0, "longitude": -40.0, "radius_km": 5})
    assert r.status_code == 200
    assert r.json() == []


async def test_nearby_search_missing_longitude_rejected(http_db):
    r = await http_db.get("/listings/search/nearby", params={"latitude": SG_LAT})
    assert r.status_code == 422


async def test_nearby_search_missing_latitude_rejected(http_db):
    r = await http_db.get("/listings/search/nearby", params={"longitude": SG_LNG})
    assert r.status_code == 422


async def test_nearby_search_invalid_latitude_rejected(http_db):
    r = await http_db.get("/listings/search/nearby", params={"latitude": 200, "longitude": SG_LNG})
    assert r.status_code == 422


async def test_nearby_search_invalid_radius_zero_rejected(http_db):
    r = await http_db.get("/listings/search/nearby", params={"latitude": SG_LAT, "longitude": SG_LNG, "radius_km": 0})
    assert r.status_code == 422


async def test_nearby_search_radius_boundary_max(http_db):
    r = await http_db.get("/listings/search/nearby", params={"latitude": SG_LAT, "longitude": SG_LNG, "radius_km": 100})
    assert r.status_code == 200


# ── Optimistic locking (lock_service) ─────────────────────────────────────────

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
    v2 = await lock_listing(lock_db, listing.id, v1, ListingStatus.AVAILABLE)
    assert v2 == 2
