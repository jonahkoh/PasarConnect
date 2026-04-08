"""
Payment Orchestrator tests.

All downstream calls are mocked:
- inventory_client gRPC calls
- payment_log_client gRPC calls
- internal HTTP helper (_post)
- RabbitMQ publisher functions
"""

import importlib.util as _ilu
import os
import sys
from types import SimpleNamespace
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
    sys.modules.setdefault("verification_pb2", MagicMock())
    sys.modules.setdefault("verification_pb2_grpc", MagicMock())
    if "payment_log_pb2" not in sys.modules:
        payment_log_pb2 = MagicMock()
        payment_log_pb2.PENDING = 1
        payment_log_pb2.SUCCESS = 2
        payment_log_pb2.COLLECTED = 3
        payment_log_pb2.REFUNDED = 4
        payment_log_pb2.FAILED = 5

        class _PaymentStatus:
            @staticmethod
            def Name(value):
                names = {
                    1: "PENDING",
                    2: "SUCCESS",
                    3: "COLLECTED",
                    4: "REFUNDED",
                    5: "FAILED",
                }
                return names.get(value, "PAYMENT_STATUS_UNSPECIFIED")

        payment_log_pb2.PaymentStatus = _PaymentStatus
        sys.modules["payment_log_pb2"] = payment_log_pb2
    sys.modules.setdefault("payment_log_pb2_grpc", MagicMock())

    # Stub shared.jwt_auth so the import inside payment.py succeeds at module load.
    _mock_jwt_fn = AsyncMock(return_value={"sub": "42"})
    _shared_jwt_mock = MagicMock()
    _shared_jwt_mock.verify_jwt_token = _mock_jwt_fn
    sys.modules.setdefault("shared", MagicMock())
    sys.modules["shared.jwt_auth"] = _shared_jwt_mock

    spec = _ilu.spec_from_file_location("payment_app", os.path.join(PAYMENT_DIR, "payment.py"))
    payment_mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(payment_mod)

    # Override JWT dependency — every test request arrives with sub="42" (user_id=42).
    payment_mod.app.dependency_overrides[payment_mod.verify_jwt_token] = lambda: {"sub": "42"}

    with (
        patch.object(payment_mod.inventory_client, "lock_listing_pending_payment", new_callable=AsyncMock) as mock_soft_lock,
        patch.object(payment_mod.inventory_client, "get_listing", new_callable=AsyncMock) as mock_get_listing,
        patch.object(payment_mod.inventory_client, "mark_listing_sold", new_callable=AsyncMock) as mock_mark_sold,
            patch.object(payment_mod.inventory_client, "mark_listing_sold_pending_collection", new_callable=AsyncMock) as mock_mark_pending_collection,
        patch.object(payment_mod.inventory_client, "rollback_listing_to_available", new_callable=AsyncMock) as mock_mark_available,
        patch.object(payment_mod.verification_client, "verify_public_user", new_callable=AsyncMock) as mock_verify_user,
        patch.object(payment_mod.payment_log_client, "create_payment_log", new_callable=AsyncMock) as mock_create_payment_log,
        patch.object(payment_mod.payment_log_client, "get_payment_log", new_callable=AsyncMock) as mock_get_payment_log,
        patch.object(payment_mod.payment_log_client, "update_payment_status_with_version", new_callable=AsyncMock) as mock_update_payment_status,
        patch.object(payment_mod.publisher, "publish_payment_success", new_callable=AsyncMock) as mock_publish_success,
        patch.object(payment_mod.publisher, "publish_payment_failure", new_callable=AsyncMock) as mock_publish_failure,
        patch.object(payment_mod.publisher, "publish_payment_collected", new_callable=AsyncMock) as mock_publish_collected,
        patch.object(payment_mod.publisher, "publish_payment_refunded", new_callable=AsyncMock) as mock_publish_refunded,
        patch.object(payment_mod, "_post", new_callable=AsyncMock) as mock_post,
    ):
        mock_soft_lock.return_value = 7
        mock_get_listing.return_value = SimpleNamespace(listed_at="", price=25.0)  # empty = window inactive
        mock_mark_sold.return_value = 10
        mock_mark_pending_collection.return_value = 9
        mock_mark_available.return_value = 8
        mock_verify_user.return_value = None  # eligible by default

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
        mock_get_payment_log.return_value = SimpleNamespace(
            status=2,
            listing_id=222,
            listing_version=5,
            amount=42.5,
            user_id=42,
            updated_at=None,
            created_at="2024-01-01T00:00:00+00:00",
        )

        client = AsyncClient(
            transport=ASGITransport(app=payment_mod.app),
            base_url="http://test",
        )
        try:
            yield {
                "client": client,
                "mock_soft_lock": mock_soft_lock,
                "mock_get_listing": mock_get_listing,
                "mock_verify_user": mock_verify_user,
                "mock_mark_sold": mock_mark_sold,
                "mock_mark_pending_collection": mock_mark_pending_collection,
                "mock_mark_available": mock_mark_available,
                "mock_create_payment_log": mock_create_payment_log,
                "mock_get_payment_log": mock_get_payment_log,
                "mock_update_payment_status": mock_update_payment_status,
                "mock_publish_success": mock_publish_success,
                "mock_publish_failure": mock_publish_failure,
                "mock_publish_collected": mock_publish_collected,
                "mock_publish_refunded": mock_publish_refunded,
                "mock_post": mock_post,
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
    # amount is now sourced from inventory listing_info.price, not the request body.
    payload = {"listing_id": 101, "listing_version": 3}

    response = await payment_client["client"].post("/payments/intent", json=payload)

    assert response.status_code == 201
    assert response.json() == {"client_secret": "pi_mock_123_secret"}
    payment_client["mock_verify_user"].assert_called_once_with(42, 101)
    payment_client["mock_get_listing"].assert_called_once_with(101)
    payment_client["mock_soft_lock"].assert_called_once_with(101, 3)
    payment_client["mock_post"].assert_called_once()
    payment_client["mock_create_payment_log"].assert_called_once_with(
        transaction_id="pi_mock_123",
        listing_id=101,
        listing_version=7,
        amount=25.0,  # sourced from listing_info.price
        user_id=42,
    )


@pytest.mark.asyncio
async def test_create_payment_intent_blocked_during_queue_window(payment_client):
    """Queue window active → 409 queue_window_active (public purchase blocked)."""
    import datetime as _dt
    # Simulate listing created 5 seconds ago; QUEUE_WINDOW default (5 min) still open
    recent = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=5)).isoformat()
    payment_client["mock_get_listing"].return_value = SimpleNamespace(listed_at=recent, price=25.0)

    # Queue window active → 409.  user_id omitted — comes from JWT.
    payload = {"listing_id": 101, "listing_version": 3}
    response = await payment_client["client"].post("/payments/intent", json=payload)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "queue_window_active"
    assert "window_closes_at" in detail
    # Inventory must NOT have been locked during the window
    payment_client["mock_soft_lock"].assert_not_called()


@pytest.mark.asyncio
async def test_create_payment_intent_no_price(payment_client):
    """Listing with price=0.0 (not set) → 422."""
    payment_client["mock_get_listing"].return_value = SimpleNamespace(listed_at="", price=0.0)

    payload = {"listing_id": 101, "listing_version": 3}
    response = await payment_client["client"].post("/payments/intent", json=payload)

    assert response.status_code == 422
    assert "no price" in response.json()["detail"].lower()
    payment_client["mock_soft_lock"].assert_not_called()


@pytest.mark.asyncio
async def test_webhook_already_processed(payment_client):
    payment_client["mock_get_payment_log"].return_value = SimpleNamespace(
        status=2,
        listing_version=7,
        amount=20.5,
    )

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
    payment_client["mock_get_payment_log"].return_value = SimpleNamespace(
        status=1,
        listing_id=202,
        listing_version=9,
        amount=30.0,
        user_id=99,
    )

    payload = {
        "stripe_transaction_id": "pi_mock_456",
        "listing_id": 202,
        "amount": 30.0,
    }
    response = await payment_client["client"].post("/webhooks/stripe", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "transaction_id": "pi_mock_456"}
    payment_client["mock_mark_pending_collection"].assert_called_once_with(202, 9)
    payment_client["mock_update_payment_status"].assert_called_once_with(
        transaction_id="pi_mock_456",
        new_status=2,
        listing_version=9,
    )
    payment_client["mock_publish_success"].assert_called_once_with(
        transaction_id="pi_mock_456",
        listing_id=202,
        user_id=99,
    )


@pytest.mark.asyncio
async def test_webhook_grpc_failure_triggers_refund_and_failure_event(payment_client):
    payment_client["mock_get_payment_log"].return_value = SimpleNamespace(
        status=1,
        listing_id=303,
        listing_version=2,
        amount=45.0,
    )
    payment_client["mock_mark_pending_collection"].side_effect = FakeAioRpcError(
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
    payment_client["mock_get_payment_log"].side_effect = FakeAioRpcError(
        grpc.StatusCode.NOT_FOUND,
        "not found",
    )

    payload = {
        "stripe_transaction_id": "pi_missing",
        "listing_id": 404,
        "amount": 10.0,
    }
    response = await payment_client["client"].post("/webhooks/stripe", json=payload)

    assert response.status_code == 404
    assert "Payment transaction not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_amount_mismatch_returns_400(payment_client):
    payment_client["mock_get_payment_log"].return_value = SimpleNamespace(
        status=1,
        listing_version=2,
        amount=99.0,
    )

    payload = {
        "stripe_transaction_id": "pi_amount_mismatch",
        "listing_id": 303,
        "amount": 45.0,
    }
    response = await payment_client["client"].post("/webhooks/stripe", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "amount_mismatch"


@pytest.mark.asyncio
async def test_approve_payment_success(payment_client):
    response = await payment_client["client"].post("/payments/pi_mock_approve/approve")

    assert response.status_code == 200
    assert response.json()["new_status"] == "COLLECTED"
    payment_client["mock_get_payment_log"].assert_called_once()
    payment_client["mock_mark_sold"].assert_called_once_with(listing_id=222, expected_version=5)
    payment_client["mock_publish_collected"].assert_called()

@pytest.mark.asyncio
async def test_reject_payment_success(payment_client):
    response = await payment_client["client"].post("/payments/pi_mock_approve/reject")

    assert response.status_code == 200
    assert response.json()["new_status"] == "REFUNDED"
    payment_client["mock_get_payment_log"].assert_called_once()
    payment_client["mock_update_payment_status"].assert_called_once_with(
        transaction_id="pi_mock_approve",
        new_status=4,
    )
    payment_client["mock_mark_available"].assert_called_once_with(listing_id=222, expected_version=5)
    payment_client["mock_publish_refunded"].assert_called()
