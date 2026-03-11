"""
Inventory Service tests — HTTP layer + optimistic locking (14 tests).
Uses in-memory SQLite so no real DB is needed.
The sys.path is managed by backend/conftest.py before each test.
"""
import sys, os

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import patch
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
