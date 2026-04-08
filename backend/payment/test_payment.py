"""
Unit tests for the Payment Service orchestrator (payment.py).

All external dependencies are mocked — no real services, DB, or network needed.
Run with:  pytest test_payment.py -v
"""
import datetime
import httpx
import grpc
import pytest
from fastapi import HTTPException
from httpx import AsyncClient, ASGITransport
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import payment_log_pb2
from payment import app
from shared.jwt_auth import verify_jwt_token
from verification_client import UserNotEligibleError

pytestmark = pytest.mark.asyncio


# ── Test helpers ───────────────────────────────────────────────────────────────

def _past(minutes: float) -> str:
    """ISO timestamp N minutes in the past."""
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    return t.isoformat()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _log(
    status=None,
    listing_id=1,
    listing_version=2,
    amount=50.0,
    user_id=42,
    updated_at=None,
):
    """Build a fake GetPaymentLogResponse-like namespace."""
    return SimpleNamespace(
        status=payment_log_pb2.SUCCESS if status is None else status,
        listing_id=listing_id,
        listing_version=listing_version,
        amount=amount,
        user_id=user_id,
        created_at=_now(),
        updated_at=_now() if updated_at is None else updated_at,
    )


def _rpc_err(code: grpc.StatusCode) -> grpc.aio.AioRpcError:
    """Real grpc.aio.AioRpcError instance so except clauses catch it correctly."""
    return grpc.aio.AioRpcError(
        code=code,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details="mocked",
    )


def _http_mock(json_resp=None, http_error=None):
    """
    Returns a mock replacing httpx.AsyncClient() as an async context manager.
    Patch as: patch("payment.httpx.AsyncClient", _http_mock(...))
    """
    resp = MagicMock()
    if http_error:
        resp.raise_for_status.side_effect = http_error
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = json_resp or {}

    client = AsyncMock()
    client.post.return_value = resp

    cls = MagicMock()
    cls.return_value.__aenter__ = AsyncMock(return_value=client)
    cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return cls


_INTENT_OK = _http_mock({"payment_intent_id": "pi_test", "client_secret": "pi_test_secret"})
_REFUND_OK = _http_mock({"refund_id": "re_test", "status": "succeeded"})
_REFUND_FAIL = _http_mock(
    http_error=httpx.HTTPStatusError("fail", request=MagicMock(), response=MagicMock())
)


async def _call(method: str, path: str, **kwargs):
    """Fire a test HTTP request against the FastAPI app."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.request(method.upper(), path, **kwargs)


def _listing_info(status="AVAILABLE", version=1, price=50.0, listed_at=""):
    """Build a fake GetListingResponse-like namespace."""
    return SimpleNamespace(status=status, version=version, price=price, listed_at=listed_at)


# ── POST /payments/intent ─────────────────────────────────────────────────────

class TestCreateIntent:
    BODY = {"user_id": 42, "listing_id": 1, "listing_version": 0, "amount": 50.0}

    @pytest.fixture(autouse=True)
    def _override_jwt(self):
        """Bypass JWT verification — user_id 42 comes from the mocked token sub claim."""
        app.dependency_overrides[verify_jwt_token] = lambda: {"sub": "42"}
        yield
        del app.dependency_overrides[verify_jwt_token]

    async def test_happy_path_returns_client_secret(self):
        with (
            patch("payment.verification_client.verify_public_user", AsyncMock()),
            patch("payment.inventory_client.get_listing", AsyncMock(return_value=_listing_info())),
            patch("payment.inventory_client.lock_listing_pending_payment", AsyncMock(return_value=2)),
            patch("payment.httpx.AsyncClient", _INTENT_OK),
            patch("payment.payment_log_client.create_payment_log", AsyncMock()),
        ):
            r = await _call("post", "/payments/intent", json=self.BODY)
        assert r.status_code == 201
        assert r.json()["client_secret"] == "pi_test_secret"

    async def test_user_ineligible_returns_403(self):
        # Fails at Step 0 — get_listing is never reached.
        with patch(
            "payment.verification_client.verify_public_user",
            AsyncMock(side_effect=UserNotEligibleError("BANNED")),
        ):
            r = await _call("post", "/payments/intent", json=self.BODY)
        assert r.status_code == 403
        assert "BANNED" in r.json()["detail"]

    async def test_listing_not_found_returns_404(self):
        with (
            patch("payment.verification_client.verify_public_user", AsyncMock()),
            patch("payment.inventory_client.get_listing", AsyncMock(return_value=_listing_info())),
            patch(
                "payment.inventory_client.lock_listing_pending_payment",
                AsyncMock(side_effect=_rpc_err(grpc.StatusCode.NOT_FOUND)),
            ),
        ):
            r = await _call("post", "/payments/intent", json=self.BODY)
        assert r.status_code == 404

    async def test_listing_already_taken_returns_409(self):
        # get_listing returns AVAILABLE so self-heal path is NOT triggered.
        with (
            patch("payment.verification_client.verify_public_user", AsyncMock()),
            patch("payment.inventory_client.get_listing", AsyncMock(return_value=_listing_info(status="AVAILABLE"))),
            patch(
                "payment.inventory_client.lock_listing_pending_payment",
                AsyncMock(side_effect=_rpc_err(grpc.StatusCode.ABORTED)),
            ),
        ):
            r = await _call("post", "/payments/intent", json=self.BODY)
        assert r.status_code == 409

    async def test_inventory_unavailable_returns_503(self):
        with (
            patch("payment.verification_client.verify_public_user", AsyncMock()),
            patch("payment.inventory_client.get_listing", AsyncMock(return_value=_listing_info())),
            patch(
                "payment.inventory_client.lock_listing_pending_payment",
                AsyncMock(side_effect=_rpc_err(grpc.StatusCode.UNAVAILABLE)),
            ),
        ):
            r = await _call("post", "/payments/intent", json=self.BODY)
        assert r.status_code == 503

    async def test_user_id_stored_in_payment_log(self):
        """user_id from the JWT must be forwarded to create_payment_log."""
        mock_create = AsyncMock()
        with (
            patch("payment.verification_client.verify_public_user", AsyncMock()),
            patch("payment.inventory_client.get_listing", AsyncMock(return_value=_listing_info())),
            patch("payment.inventory_client.lock_listing_pending_payment", AsyncMock(return_value=2)),
            patch("payment.httpx.AsyncClient", _INTENT_OK),
            patch("payment.payment_log_client.create_payment_log", mock_create),
        ):
            await _call("post", "/payments/intent", json=self.BODY)
        _, kwargs = mock_create.call_args
        assert kwargs["user_id"] == 42

    # ── Fix 4: self-heal tests ────────────────────────────────────────────────

    async def test_self_heal_succeeds_when_stuck_pending_payment(self):
        """
        If get_listing reports PENDING_PAYMENT and lock returns ABORTED, the
        endpoint rolls back the stale lock and retries — returning 201.
        """
        stuck = _listing_info(status="PENDING_PAYMENT", version=3)
        mock_rollback = AsyncMock(return_value=4)   # rollback succeeds → version 4
        mock_lock     = AsyncMock(side_effect=[
            _rpc_err(grpc.StatusCode.ABORTED),  # first attempt: listing is locked
            5,                                   # retry after rollback: succeeds
        ])
        with (
            patch("payment.verification_client.verify_public_user", AsyncMock()),
            patch("payment.inventory_client.get_listing", AsyncMock(return_value=stuck)),
            patch("payment.inventory_client.lock_listing_pending_payment", mock_lock),
            patch("payment.inventory_client.rollback_listing_to_available", mock_rollback),
            patch("payment.httpx.AsyncClient", _INTENT_OK),
            patch("payment.payment_log_client.create_payment_log", AsyncMock()),
        ):
            r = await _call("post", "/payments/intent", json=self.BODY)
        assert r.status_code == 201
        mock_rollback.assert_awaited_once_with(1, 3)   # listing_id=1, version=3
        assert mock_lock.await_count == 2              # initial attempt + retry

    async def test_self_heal_fails_returns_409(self):
        """If the rollback itself fails during self-heal, return 409 gracefully."""
        stuck = _listing_info(status="PENDING_PAYMENT", version=3)
        with (
            patch("payment.verification_client.verify_public_user", AsyncMock()),
            patch("payment.inventory_client.get_listing", AsyncMock(return_value=stuck)),
            patch(
                "payment.inventory_client.lock_listing_pending_payment",
                AsyncMock(side_effect=_rpc_err(grpc.StatusCode.ABORTED)),
            ),
            patch(
                "payment.inventory_client.rollback_listing_to_available",
                AsyncMock(side_effect=_rpc_err(grpc.StatusCode.ABORTED)),
            ),
        ):
            r = await _call("post", "/payments/intent", json=self.BODY)
        assert r.status_code == 409

    async def test_self_heal_skipped_when_get_listing_unavailable(self):
        """If get_listing failed (listing_info=None), ABORTED still returns 409 (no self-heal)."""
        with (
            patch("payment.verification_client.verify_public_user", AsyncMock()),
            patch(
                "payment.inventory_client.get_listing",
                AsyncMock(side_effect=Exception("service down")),
            ),
            patch(
                "payment.inventory_client.lock_listing_pending_payment",
                AsyncMock(side_effect=_rpc_err(grpc.StatusCode.ABORTED)),
            ),
        ):
            # get_listing fails → listing_price=0 → 422 (no price guard bypassed)
            r = await _call("post", "/payments/intent", json=self.BODY)
        assert r.status_code == 422  # 422 because listing_price stayed 0 after get_listing error


# ── POST /webhooks/stripe ─────────────────────────────────────────────────────

class TestStripeWebhook:
    BODY = {"stripe_transaction_id": "pi_test", "amount": 50.0}

    async def test_happy_path_returns_ok(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.PENDING))),
            patch("payment.inventory_client.mark_listing_sold_pending_collection", AsyncMock(return_value=3)),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.publisher.publish_payment_success", AsyncMock()),
        ):
            r = await _call("post", "/webhooks/stripe", json=self.BODY)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    async def test_idempotent_already_success(self):
        with patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.SUCCESS))):
            r = await _call("post", "/webhooks/stripe", json=self.BODY)
        assert r.status_code == 200
        assert r.json()["status"] == "already_processed"

    async def test_idempotent_already_refunded(self):
        with patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.REFUNDED))):
            r = await _call("post", "/webhooks/stripe", json=self.BODY)
        assert r.status_code == 200
        assert r.json()["status"] == "already_processed"

    async def test_idempotent_already_forfeited(self):
        with patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.FORFEITED))):
            r = await _call("post", "/webhooks/stripe", json=self.BODY)
        assert r.status_code == 200
        assert r.json()["status"] == "already_processed"

    async def test_amount_mismatch_returns_400(self):
        with patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.PENDING, amount=99.0))):
            r = await _call("post", "/webhooks/stripe", json=self.BODY)  # body amount=50.0
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "amount_mismatch"

    async def test_inventory_failure_triggers_compensating_refund(self):
        mock_fail = AsyncMock()
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.PENDING))),
            patch("payment.inventory_client.mark_listing_sold_pending_collection", AsyncMock(side_effect=_rpc_err(grpc.StatusCode.UNAVAILABLE))),
            patch("payment.httpx.AsyncClient", _REFUND_OK),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock()),
            patch("payment.publisher.publish_payment_failure", mock_fail),
            patch("payment.publisher.publish_payment_refunded", AsyncMock()),
        ):
            r = await _call("post", "/webhooks/stripe", json=self.BODY)
        assert r.status_code == 503
        body = r.json()["detail"]
        assert body["refunded"] is True
        assert body["error"] == "inventory_unavailable"
        mock_fail.assert_awaited_once()

    async def test_inventory_failure_notifies_buyer_when_refund_succeeds(self):
        """publish_payment_refunded must fire with the buyer's user_id when Stripe refund succeeds."""
        mock_refunded = AsyncMock()
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.PENDING))),
            patch("payment.inventory_client.mark_listing_sold_pending_collection", AsyncMock(side_effect=_rpc_err(grpc.StatusCode.UNAVAILABLE))),
            patch("payment.httpx.AsyncClient", _REFUND_OK),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock()),
            patch("payment.publisher.publish_payment_failure", AsyncMock()),
            patch("payment.publisher.publish_payment_refunded", mock_refunded),
        ):
            await _call("post", "/webhooks/stripe", json=self.BODY)
        mock_refunded.assert_awaited_once()
        _, kwargs = mock_refunded.call_args
        assert kwargs["user_id"] == 42       # matches _log() default user_id
        assert "reason" in kwargs

    async def test_inventory_failure_does_not_notify_buyer_when_refund_fails(self):
        """publish_payment_refunded must NOT fire when Stripe refund itself fails."""
        mock_refunded = AsyncMock()
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.PENDING))),
            patch("payment.inventory_client.mark_listing_sold_pending_collection", AsyncMock(side_effect=_rpc_err(grpc.StatusCode.UNAVAILABLE))),
            patch("payment.httpx.AsyncClient", _REFUND_FAIL),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock()),
            patch("payment.publisher.publish_payment_failure", AsyncMock()),
            patch("payment.publisher.publish_payment_refunded", mock_refunded),
        ):
            await _call("post", "/webhooks/stripe", json=self.BODY)
        mock_refunded.assert_not_awaited()

    async def test_transaction_not_found_returns_404(self):
        with patch(
            "payment.payment_log_client.get_payment_log",
            AsyncMock(side_effect=HTTPException(status_code=404, detail="Payment transaction not found")),
        ):
            r = await _call("post", "/webhooks/stripe", json=self.BODY)
        assert r.status_code == 404


# ── POST /payments/{id}/approve ───────────────────────────────────────────────

class TestApprovePayment:
    TXN = "pi_test"

    async def test_happy_path_returns_collected(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log())),
            patch("payment.inventory_client.mark_listing_sold", AsyncMock(return_value=3)),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.publisher.publish_payment_success", AsyncMock()),
        ):
            r = await _call("post", f"/payments/{self.TXN}/approve")
        assert r.status_code == 200
        assert r.json()["new_status"] == "COLLECTED"

    async def test_not_success_returns_409(self):
        with patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.REFUNDED))):
            r = await _call("post", f"/payments/{self.TXN}/approve")
        assert r.status_code == 409

    async def test_inventory_version_conflict_returns_409(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log())),
            patch("payment.inventory_client.mark_listing_sold", AsyncMock(side_effect=_rpc_err(grpc.StatusCode.ABORTED))),
        ):
            r = await _call("post", f"/payments/{self.TXN}/approve")
        assert r.status_code == 409

    async def test_listing_not_found_during_approve_returns_404(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log())),
            patch("payment.inventory_client.mark_listing_sold", AsyncMock(side_effect=_rpc_err(grpc.StatusCode.NOT_FOUND))),
        ):
            r = await _call("post", f"/payments/{self.TXN}/approve")
        assert r.status_code == 404


# ── POST /payments/{id}/reject ────────────────────────────────────────────────

class TestRejectPayment:
    TXN = "pi_test"

    async def test_reject_within_window_no_warning(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(updated_at=_now()))),
            patch("payment.httpx.AsyncClient", _REFUND_OK),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock(return_value=1)),
            patch("payment.publisher.publish_payment_failure", AsyncMock()),
        ):
            r = await _call("post", f"/payments/{self.TXN}/reject")
        assert r.status_code == 200
        body = r.json()
        assert body["new_status"] == "REFUNDED"
        assert "vendor_warning" not in body

    async def test_reject_past_window_includes_warning(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(updated_at=_past(2)))),
            patch("payment.httpx.AsyncClient", _REFUND_OK),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock(return_value=1)),
            patch("payment.publisher.publish_payment_failure", AsyncMock()),
        ):
            r = await _call("post", f"/payments/{self.TXN}/reject")
        assert r.status_code == 200
        assert "vendor_warning" in r.json()

    async def test_not_success_returns_409(self):
        with patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.COLLECTED))):
            r = await _call("post", f"/payments/{self.TXN}/reject")
        assert r.status_code == 409

    async def test_stripe_refund_fails_returns_503(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log())),
            patch("payment.httpx.AsyncClient", _REFUND_FAIL),
        ):
            r = await _call("post", f"/payments/{self.TXN}/reject")
        assert r.status_code == 503


# ── POST /payments/{id}/cancel ────────────────────────────────────────────────

class TestCancelPayment:
    TXN = "pi_test"
    BODY = {"user_id": 42}

    async def test_cancel_within_window_refunds(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(updated_at=_now()))),
            patch("payment.httpx.AsyncClient", _REFUND_OK),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock(return_value=1)),
            patch("payment.publisher.publish_payment_failure", AsyncMock()),
        ):
            r = await _call("post", f"/payments/{self.TXN}/cancel", json=self.BODY)
        assert r.status_code == 200
        assert r.json()["new_status"] == "REFUNDED"

    async def test_cancel_wrong_user_id_returns_403(self):
        with patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(user_id=99))):
            r = await _call("post", f"/payments/{self.TXN}/cancel", json=self.BODY)  # body user_id=42
        assert r.status_code == 403
        assert "does not match" in r.json()["detail"]

    async def test_cancel_after_window_returns_409(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(updated_at=_past(2)))),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock(return_value=1)),
        ):
            r = await _call("post", f"/payments/{self.TXN}/cancel", json=self.BODY)
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "cancellation_window_expired"

    async def test_cancel_after_window_sets_forfeited(self):
        """Past the window: payment log must be updated to FORFEITED before 409 is raised."""
        mock_update = AsyncMock()
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(updated_at=_past(2)))),
            patch("payment.payment_log_client.update_payment_status_with_version", mock_update),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock(return_value=1)),
        ):
            r = await _call("post", f"/payments/{self.TXN}/cancel", json=self.BODY)
        assert r.status_code == 409
        mock_update.assert_awaited_once()
        _, kwargs = mock_update.call_args
        assert kwargs["new_status"] == payment_log_pb2.FORFEITED

    async def test_cancel_after_window_rolls_back_inventory(self):
        """Past the window: inventory must be rolled back to AVAILABLE."""
        mock_rollback = AsyncMock(return_value=1)
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(updated_at=_past(2)))),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", mock_rollback),
        ):
            r = await _call("post", f"/payments/{self.TXN}/cancel", json=self.BODY)
        assert r.status_code == 409
        mock_rollback.assert_awaited_once()

    async def test_cancel_not_success_returns_409(self):
        with patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.REFUNDED))):
            r = await _call("post", f"/payments/{self.TXN}/cancel", json=self.BODY)
        assert r.status_code == 409

    async def test_cancel_stripe_refund_fails_returns_503(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(updated_at=_now()))),
            patch("payment.httpx.AsyncClient", _REFUND_FAIL),
        ):
            r = await _call("post", f"/payments/{self.TXN}/cancel", json=self.BODY)
        assert r.status_code == 503

    async def test_cancel_transaction_not_found_returns_404(self):
        with patch(
            "payment.payment_log_client.get_payment_log",
            AsyncMock(side_effect=HTTPException(status_code=404, detail="Payment transaction not found")),
        ):
            r = await _call("post", f"/payments/{self.TXN}/cancel", json=self.BODY)
        assert r.status_code == 404


# ── POST /payments/{id}/noshow ────────────────────────────────────────────────

class TestNoshowPayment:
    TXN = "pi_test"
    BODY = {"user_id": 42}

    async def test_noshow_within_window_refunds(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(updated_at=_now()))),
            patch("payment.httpx.AsyncClient", _REFUND_OK),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock(return_value=1)),
            patch("payment.verification_client.record_user_noshow", AsyncMock()),
            patch("payment.publisher.publish_payment_failure", AsyncMock()),
        ):
            r = await _call("post", f"/payments/{self.TXN}/noshow", json=self.BODY)
        assert r.status_code == 200
        body = r.json()
        assert body["refunded"] is True
        assert body["new_status"] == "REFUNDED"

    async def test_noshow_past_window_forfeits(self):
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(updated_at=_past(2)))),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock(return_value=1)),
            patch("payment.verification_client.record_user_noshow", AsyncMock()),
            patch("payment.publisher.publish_payment_failure", AsyncMock()),
        ):
            r = await _call("post", f"/payments/{self.TXN}/noshow", json=self.BODY)
        assert r.status_code == 200
        body = r.json()
        assert body["refunded"] is False
        assert body["new_status"] == "FORFEITED"

    async def test_noshow_wrong_user_id_returns_403(self):
        with patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(user_id=99))):
            r = await _call("post", f"/payments/{self.TXN}/noshow", json=self.BODY)  # body user_id=42
        assert r.status_code == 403
        assert "does not match" in r.json()["detail"]

    async def test_noshow_not_success_returns_409(self):
        with patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(status=payment_log_pb2.FORFEITED))):
            r = await _call("post", f"/payments/{self.TXN}/noshow", json=self.BODY)
        assert r.status_code == 409

    async def test_noshow_records_user_in_verification(self):
        """Verification record_user_noshow must be called with the correct user_id and transaction_id."""
        mock_record = AsyncMock()
        with (
            patch("payment.payment_log_client.get_payment_log", AsyncMock(return_value=_log(updated_at=_past(2)))),
            patch("payment.payment_log_client.update_payment_status_with_version", AsyncMock()),
            patch("payment.inventory_client.rollback_listing_to_available", AsyncMock(return_value=1)),
            patch("payment.verification_client.record_user_noshow", mock_record),
            patch("payment.publisher.publish_payment_failure", AsyncMock()),
        ):
            await _call("post", f"/payments/{self.TXN}/noshow", json=self.BODY)
        mock_record.assert_awaited_once_with(user_id=42, transaction_id=self.TXN)

    async def test_noshow_transaction_not_found_returns_404(self):
        with patch(
            "payment.payment_log_client.get_payment_log",
            AsyncMock(side_effect=HTTPException(status_code=404, detail="Payment transaction not found")),
        ):
            r = await _call("post", f"/payments/{self.TXN}/noshow", json=self.BODY)
        assert r.status_code == 404


# ── DELETE /payments/{id}/intent ─────────────────────────────────────────────

class TestAbandonPaymentIntent:
    TXN  = "pi_test"
    BODY = {"user_id": 42}

    async def test_abandon_pending_rolls_back_and_marks_refunded(self):
        """Happy path: PENDING intent rolls back inventory and marks log REFUNDED."""
        mock_update   = AsyncMock()
        mock_rollback = AsyncMock(return_value=1)
        with (
            patch("payment.payment_log_client.get_payment_log",
                  AsyncMock(return_value=_log(status=payment_log_pb2.PENDING))),
            patch("payment.inventory_client.rollback_listing_to_available", mock_rollback),
            patch("payment.payment_log_client.update_payment_status_with_version", mock_update),
        ):
            r = await _call("delete", f"/payments/{self.TXN}/intent", json=self.BODY)
        assert r.status_code == 200
        assert r.json()["status"] == "abandoned"
        mock_rollback.assert_awaited_once()
        mock_update.assert_awaited_once()

    async def test_abandon_refunded_rolls_back_but_skips_log_update(self):
        """REFUNDED status (stuck after inventory outage): rollback inventory, skip log update."""
        mock_update   = AsyncMock()
        mock_rollback = AsyncMock(return_value=1)
        with (
            patch("payment.payment_log_client.get_payment_log",
                  AsyncMock(return_value=_log(status=payment_log_pb2.REFUNDED))),
            patch("payment.inventory_client.rollback_listing_to_available", mock_rollback),
            patch("payment.payment_log_client.update_payment_status_with_version", mock_update),
        ):
            r = await _call("delete", f"/payments/{self.TXN}/intent", json=self.BODY)
        assert r.status_code == 200
        mock_rollback.assert_awaited_once()
        mock_update.assert_not_awaited()  # already REFUNDED — no log update needed

    async def test_abandon_collected_returns_409(self):
        """Terminal statuses cannot be abandoned."""
        with patch("payment.payment_log_client.get_payment_log",
                   AsyncMock(return_value=_log(status=payment_log_pb2.COLLECTED))):
            r = await _call("delete", f"/payments/{self.TXN}/intent", json=self.BODY)
        assert r.status_code == 409

    async def test_abandon_forfeited_returns_409(self):
        with patch("payment.payment_log_client.get_payment_log",
                   AsyncMock(return_value=_log(status=payment_log_pb2.FORFEITED))):
            r = await _call("delete", f"/payments/{self.TXN}/intent", json=self.BODY)
        assert r.status_code == 409

    async def test_abandon_wrong_user_returns_403(self):
        with patch("payment.payment_log_client.get_payment_log",
                   AsyncMock(return_value=_log(status=payment_log_pb2.PENDING, user_id=99))):
            r = await _call("delete", f"/payments/{self.TXN}/intent", json=self.BODY)
        assert r.status_code == 403
        assert "does not match" in r.json()["detail"]
