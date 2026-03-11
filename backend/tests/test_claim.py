"""
Claim Service tests (6 tests).
The gRPC client and RabbitMQ publisher are mocked so no real services are needed.
Uses in-memory SQLite for the claim DB.
The sys.path is managed by backend/conftest.py before each test.
"""
import sys, os

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
import grpc

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture()
async def claim_client():
    """
    Patches:
      - claim's database.engine  → SQLite in-memory
      - inventory_client.lock_listing_pending_collection → AsyncMock (returns version 2)
      - publisher.publish_claim_success → regular Mock (silences RabbitMQ)
    """
    import database as claim_db_module
    # Load claim.py by file path to avoid the name clash with the claim/ directory
    # (when backend/ is in sys.path, 'import claim' resolves to the directory).
    import importlib.util as _ilu
    _claim_path = os.path.join(os.path.dirname(__file__), "..", "claim")
    _spec = _ilu.spec_from_file_location("claim_app", os.path.join(_claim_path, "claim.py"))
    _claim_mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_claim_mod)
    app = _claim_mod.app
    from models import Base as ClaimBase

    test_engine  = create_async_engine(SQLITE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession  = async_sessionmaker(test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(ClaimBase.metadata.create_all)

    async def override_get_db():
        async with TestSession() as session:
            yield session

    with patch.object(claim_db_module, "engine", test_engine):
        get_db = claim_db_module.get_db
        app.dependency_overrides[get_db] = override_get_db

        with patch("inventory_client.lock_listing_pending_collection", new_callable=AsyncMock) as mock_lock, \
             patch("publisher.publish_claim_success") as mock_pub:

            mock_lock.return_value = 2  # Inventory returns new_version=2 by default
            yield {"client": AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
                   "mock_lock": mock_lock,
                   "mock_pub":  mock_pub}

        app.dependency_overrides.clear()

    await test_engine.dispose()


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_health(claim_client):
    async with claim_client["client"] as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


async def test_create_claim_success(claim_client):
    async with claim_client["client"] as c:
        r = await c.post("/claims", json={"listing_id": 1, "charity_id": 42, "listing_version": 1})
    assert r.status_code == 201
    data = r.json()
    assert data["listing_id"]  == 1
    assert data["charity_id"]  == 42
    assert data["status"]      == "PENDING"
    assert data["listing_version"] == 2   # stored new_version from Inventory


async def test_create_claim_publishes_event(claim_client):
    async with claim_client["client"] as c:
        await c.post("/claims", json={"listing_id": 5, "charity_id": 10, "listing_version": 1})
    claim_client["mock_pub"].assert_called_once()
    args = claim_client["mock_pub"].call_args[0]
    assert args[1] == 5   # listing_id
    assert args[2] == 10  # charity_id


async def test_create_claim_listing_not_found(claim_client):
    claim_client["mock_lock"].side_effect = grpc.aio.AioRpcError(
        grpc.StatusCode.NOT_FOUND, None, None
    )
    async with claim_client["client"] as c:
        r = await c.post("/claims", json={"listing_id": 999, "charity_id": 1, "listing_version": 1})
    assert r.status_code == 404


async def test_create_claim_already_claimed(claim_client):
    claim_client["mock_lock"].side_effect = grpc.aio.AioRpcError(
        grpc.StatusCode.ABORTED, None, None
    )
    async with claim_client["client"] as c:
        r = await c.post("/claims", json={"listing_id": 1, "charity_id": 1, "listing_version": 1})
    assert r.status_code == 409


async def test_create_claim_inventory_unavailable(claim_client):
    claim_client["mock_lock"].side_effect = grpc.aio.AioRpcError(
        grpc.StatusCode.UNAVAILABLE, None, None
    )
    async with claim_client["client"] as c:
        r = await c.post("/claims", json={"listing_id": 1, "charity_id": 1, "listing_version": 1})
    assert r.status_code == 503
