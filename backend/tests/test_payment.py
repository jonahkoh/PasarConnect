"""
Payment Orchestrator tests.

All downstream calls are mocked:
- inventory_client gRPC calls
- internal HTTP helpers (_get/_post/_patch)
- RabbitMQ publisher functions
"""

import importlib.util as _ilu
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

PAYMENT_DIR = os.path.join(os.path.dirname(__file__), "..", "payment")


class FakeAioRpcError(grpc.aio.AioRpcError):
    """Minimal grpc.aio.AioRpcError test double with code/details only."""

    def __init__(self, status_code: grpc.StatusCode, message: str):
        self._status_code = status_code
        self._message = message

    def code(self):
        return self._status_code

    def details(self):
        return self._message


@pytest_asyncio.fixture()
async def payment_client():
    # Stub generated gRPC modules so tests do not require protoc output.
    sys.modules.setdefault("inventory_pb2", MagicMock())
    sys.modules.setdefault("inventory_pb2_grpc", MagicMock())

    spec = _ilu.spec_from_file_location("payment_app", os.path.join(PAYMENT_DIR, "payment.py"))
    payment_mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(payment_mod)

    with (
        patch.object(payment_mod.inventory_client, "lock_listing_pending_payment", new_callable=AsyncMock) as mock_soft_lock,
        patch.object(payment_mod.inventory_client, "mark_listing_sold", new_callable=AsyncMock) as mock_mark_sold,
        patch.object(payment_mod.publisher, "publish_payment_success", new_callable=AsyncMock) as mock_publish_success,
        patch.object(payment_mod.publisher, "publish_payment_failure", new_callable=AsyncMock) as mock_publish_failure,
        patch.object(payment_mod, "_post", new_callable=AsyncMock) as mock_post,
        patch.object(payment_mod, "_get", new_callable=AsyncMock) as mock_get,
        patch.object(payment_mod, "_patch", new_callable=AsyncMock) as mock_patch,
    ):
        mock_soft_lock.return_value = 7

        async def _post_side_effect(_client, url, _body):
            if url.endswith("/stripe/intent"):
                return {
                    "payment_intent_id": "pi_mock_123",
                    "client_secret": "pi_mock_123_secret",
                }
            if url.endswith("/stripe/refund"):
                return {"refund_id": "re_mock_123", "status": "succeeded"}
            if url.endswith("/logs"):
                return {"status": "PENDING"}
            return {}

        mock_post.side_effect = _post_side_effect
        mock_patch.return_value = {"status": "SUCCESS"}

        client = AsyncClient(
            transport=ASGITransport(app=payment_mod.app),
            base_url="http://test",
        )
        try:
            yield {
                "client": client,
                "mock_soft_lock": mock_soft_lock,
                "mock_mark_sold": mock_mark_sold,
                "mock_publish_success": mock_publish_success,
                "mock_publish_failure": mock_publish_failure,
                "mock_get": mock_get,
                "mock_post": mock_post,
                "mock_patch": mock_patch,
            }
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_health(payment_client):
    response = await payment_client["client"].get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "payment"}


@pytest.mark.asyncio
async def test_create_payment_intent_success(payment_client):
    payload = {"listing_id": 101, "listing_version": 3, "amount": 20.5}

    response = await payment_client["client"].post("/payments/intent", json=payload)

    assert response.status_code == 201
    assert response.json() == {"client_secret": "pi_mock_123_secret"}
    payment_client["mock_soft_lock"].assert_called_once_with(101, 3)
    assert payment_client["mock_post"].call_count == 2


@pytest.mark.asyncio
async def test_webhook_already_processed(payment_client):
    payment_client["mock_get"].return_value = {
        "status": "SUCCESS",
        "listing_version": 7,
    }

    payload = {
        "stripe_transaction_id": "pi_mock_123",
        "listing_id": 101,
        "amount": 20.5,
    }
    response = await payment_client["client"].post("/webhooks/stripe", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "already_processed"}
    payment_client["mock_mark_sold"].assert_not_called()


@pytest.mark.asyncio
async def test_webhook_success_path(payment_client):
    payment_client["mock_get"].return_value = {
        "status": "PENDING",
        "listing_version": 9,
    }

    payload = {
        "stripe_transaction_id": "pi_mock_456",
        "listing_id": 202,
        "amount": 30.0,
    }
    response = await payment_client["client"].post("/webhooks/stripe", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "transaction_id": "pi_mock_456"}
    payment_client["mock_mark_sold"].assert_called_once_with(202, 9)
    payment_client["mock_patch"].assert_called_once()
    payment_client["mock_publish_success"].assert_called_once_with(
        transaction_id="pi_mock_456",
        listing_id=202,
    )


@pytest.mark.asyncio
async def test_webhook_grpc_failure_triggers_refund_and_failure_event(payment_client):
    payment_client["mock_get"].return_value = {
        "status": "PENDING",
        "listing_version": 2,
    }
    payment_client["mock_mark_sold"].side_effect = FakeAioRpcError(
        grpc.StatusCode.UNAVAILABLE,
        "inventory unavailable",
    )

    payload = {
        "stripe_transaction_id": "pi_mock_789",
        "listing_id": 303,
        "amount": 45.0,
    }
    response = await payment_client["client"].post("/webhooks/stripe", json=payload)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "inventory_unavailable"
    assert detail["transaction_id"] == "pi_mock_789"
    assert detail["refunded"] is True
    payment_client["mock_publish_failure"].assert_called_once()


@pytest.mark.asyncio
async def test_webhook_log_missing_returns_404(payment_client):
    payment_client["mock_get"].return_value = None

    payload = {
        "stripe_transaction_id": "pi_missing",
        "listing_id": 404,
        "amount": 10.0,
    }
    response = await payment_client["client"].post("/webhooks/stripe", json=payload)

    assert response.status_code == 404
    assert "Payment record not found" in response.json()["detail"]
