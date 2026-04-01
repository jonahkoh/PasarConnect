"""
Listing Service tests.

The listing composite service is stateless, so tests mock:
- inventory create client call
- RabbitMQ publish helper
"""

import importlib.util as _ilu
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

LISTING_DIR = os.path.join(os.path.dirname(__file__), "..", "listing")


@pytest_asyncio.fixture()
async def listing_client():
    # Ensure sibling imports in listing service resolve during direct module load.
    if LISTING_DIR not in sys.path:
        sys.path.insert(0, LISTING_DIR)

    spec = _ilu.spec_from_file_location("listing_app", os.path.join(LISTING_DIR, "listing.py"))
    listing_mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(listing_mod)

    with (
        patch.object(listing_mod.inventory_client, "create_listing", new_callable=AsyncMock) as mock_create,
        patch.object(listing_mod, "_publish_created_events", new_callable=AsyncMock) as mock_publish,
    ):
        mock_create.return_value = 123

        client = AsyncClient(
            transport=ASGITransport(app=listing_mod.app),
            base_url="http://test",
        )
        try:
            yield {
                "client": client,
                "mock_create": mock_create,
                "mock_publish": mock_publish,
                "listing_mod": listing_mod,
            }
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_health(listing_client):
    response = await listing_client["client"].get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "listing"}


@pytest.mark.asyncio
async def test_create_listing_success(listing_client):
    payload = {
        "vendor_id": "vendor_42",
        "title": "Fresh Bread",
        "description": "Whole loaf",
        "quantity": 2,
        "weight_kg": 1.5,
        "expiry": "2099-12-31T12:00:00Z",
        "image_url": "https://example.com/bread.jpg",
    }

    response = await listing_client["client"].post("/api/listings", json=payload)

    assert response.status_code == 201
    assert response.json() == {"listing_id": 123}
    listing_client["mock_create"].assert_called_once()
    listing_client["mock_publish"].assert_called_once_with(123)


@pytest.mark.asyncio
async def test_create_listing_validation_error(listing_client):
    payload = {
        "vendor_id": "",
        "title": "",
        "description": "x",
        "quantity": None,
        "weight_kg": None,
        "expiry": "not-a-date",
        "image_url": "",
    }

    response = await listing_client["client"].post("/api/listings", json=payload)

    assert response.status_code == 422
    listing_client["mock_create"].assert_not_called()
    listing_client["mock_publish"].assert_not_called()


@pytest.mark.asyncio
async def test_create_listing_inventory_unavailable(listing_client):
    listing_client["mock_create"].side_effect = listing_client["listing_mod"].inventory_client.InventoryServiceError(
        "Inventory service unavailable"
    )

    payload = {
        "vendor_id": "vendor_7",
        "title": "Apple",
        "description": "Fresh",
        "quantity": 3,
        "weight_kg": None,
        "expiry": "2099-12-31T12:00:00Z",
        "image_url": "https://example.com/apple.jpg",
    }

    response = await listing_client["client"].post("/api/listings", json=payload)

    assert response.status_code == 503
    assert response.json()["detail"] == "Inventory service unavailable"
    listing_client["mock_publish"].assert_not_called()


@pytest.mark.asyncio
async def test_create_listing_publish_failure_returns_503(listing_client):
    listing_client["mock_publish"].side_effect = RuntimeError("rabbit down")

    payload = {
        "vendor_id": "vendor_9",
        "title": "Banana",
        "description": "Yellow",
        "quantity": 6,
        "weight_kg": None,
        "expiry": "2099-12-31T12:00:00Z",
        "image_url": "https://example.com/banana.jpg",
    }

    response = await listing_client["client"].post("/api/listings", json=payload)

    assert response.status_code == 503
    assert response.json()["detail"] == "RabbitMQ publish failed"


@pytest.mark.asyncio
async def test_create_listing_inventory_unsuccessful_returns_500(listing_client):
    listing_client["mock_create"].side_effect = listing_client["listing_mod"].inventory_client.InventoryServiceError(
        "Inventory failed to create listing",
        status_code=500,
    )

    payload = {
        "vendor_id": "vendor_13",
        "title": "Yogurt",
        "description": "Dairy",
        "quantity": None,
        "weight_kg": 2.0,
        "expiry": "2099-12-31T12:00:00Z",
        "image_url": "https://example.com/yogurt.jpg",
    }

    response = await listing_client["client"].post("/api/listings", json=payload)

    assert response.status_code == 500
    assert response.json()["detail"] == "Inventory failed to create listing"
    listing_client["mock_publish"].assert_not_called()
