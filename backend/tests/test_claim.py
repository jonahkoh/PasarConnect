"""
Claim Orchestrator tests.

The orchestrator is stateless, so tests mock all downstream integrations:
- verification call helper
- inventory gRPC lock/rollback helpers
- claim-log HTTP helper
- RabbitMQ publisher methods
"""

import importlib.util as _ilu
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, TimeoutException

CLAIM_DIR = os.path.join(os.path.dirname(__file__), "..", "claim")


class FakeAioRpcError(grpc.aio.AioRpcError):
    def __init__(self, status_code: grpc.StatusCode, message: str):
        self._status_code = status_code
        self._message = message

    def code(self):
        return self._status_code

    def details(self):
        return self._message


@pytest_asyncio.fixture()
async def claim_client():
    # Stub generated gRPC modules so tests do not require protoc output.
    sys.modules.setdefault("inventory_pb2", MagicMock())
    sys.modules.setdefault("inventory_pb2_grpc", MagicMock())

    spec = _ilu.spec_from_file_location("claim_app", os.path.join(CLAIM_DIR, "claim.py"))
    claim_mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(claim_mod)

    with (
        patch.object(claim_mod, "_verify_claim_eligibility", new_callable=AsyncMock) as mock_verify,
        patch.object(claim_mod.inventory_client, "lock_listing_pending_collection", new_callable=AsyncMock) as mock_lock,
        patch.object(claim_mod.inventory_client, "rollback_listing_to_available", new_callable=AsyncMock) as mock_rollback,
        patch.object(claim_mod, "_post", new_callable=AsyncMock) as mock_post,
        patch.object(claim_mod.publisher, "publish_claim_success", new_callable=AsyncMock) as mock_pub_success,
        patch.object(claim_mod.publisher, "publish_claim_failure", new_callable=AsyncMock) as mock_pub_failure,
    ):
        mock_verify.return_value = None
        mock_lock.return_value = 4
        mock_rollback.return_value = 5

        mock_post.return_value = {
            "id": 11,
            "listing_id": 1,
            "charity_id": 42,
            "listing_version": 4,
            "status": "PENDING_COLLECTION",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": None,
        }

        client = AsyncClient(
            transport=ASGITransport(app=claim_mod.app),
            base_url="http://test",
        )
        try:
            yield {
                "client": client,
                "mock_verify": mock_verify,
                "mock_lock": mock_lock,
                "mock_rollback": mock_rollback,
                "mock_post": mock_post,
                "mock_pub_success": mock_pub_success,
                "mock_pub_failure": mock_pub_failure,
            }
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_health(claim_client):
    response = await claim_client["client"].get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "claim"}


@pytest.mark.asyncio
async def test_create_claim_success(claim_client):
    payload = {"listing_id": 1, "charity_id": 42, "listing_version": 1}

    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 201
    assert response.json()["status"] == "PENDING_COLLECTION"
    claim_client["mock_verify"].assert_called_once_with(42, 1)
    claim_client["mock_lock"].assert_called_once_with(listing_id=1, expected_version=1)
    claim_client["mock_pub_success"].assert_called_once()
    claim_client["mock_pub_failure"].assert_not_called()


@pytest.mark.asyncio
async def test_create_claim_listing_not_found(claim_client):
    claim_client["mock_lock"].side_effect = FakeAioRpcError(grpc.StatusCode.NOT_FOUND, "no listing")

    payload = {"listing_id": 999, "charity_id": 1, "listing_version": 0}
    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_claim_already_claimed(claim_client):
    claim_client["mock_lock"].side_effect = FakeAioRpcError(grpc.StatusCode.ABORTED, "version mismatch")

    payload = {"listing_id": 1, "charity_id": 1, "listing_version": 0}
    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_claim_inventory_unavailable(claim_client):
    claim_client["mock_lock"].side_effect = FakeAioRpcError(grpc.StatusCode.UNAVAILABLE, "down")

    payload = {"listing_id": 1, "charity_id": 1, "listing_version": 0}
    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_claim_log_timeout_triggers_compensation(claim_client):
    claim_client["mock_post"].side_effect = TimeoutException("timeout")

    payload = {"listing_id": 7, "charity_id": 9, "listing_version": 2}
    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "claim_log_unavailable"
    assert detail["inventory_rollback_succeeded"] is True
    claim_client["mock_rollback"].assert_called_once_with(7, 4)
    claim_client["mock_pub_failure"].assert_called_once()
