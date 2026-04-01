"""
Claim Orchestrator tests.

The orchestrator coordinates Verification (gRPC), Inventory (gRPC),
Claim Log (gRPC), Waitlist DB, and RabbitMQ.  All downstream integrations
are mocked so tests run without any real services.

Fixture design
──────────────
• waitlist_db and waitlist_router are injected into sys.modules *before*
  claim.py is loaded, so their module-level side-effects (engine creation,
  router registration) and the lifespan init_db() call are fully controlled.
• shared.jwt_auth is mocked so the JWT RS256 dependency can be overridden
  per-test via app.dependency_overrides.
• The default JWT mock returns {"sub": "42"}, matching the charity_id=42
  used in the happy-path tests.  Tests that need a different sub or a
  deliberate mismatch override the dependency themselves.
"""

import importlib.util as _ilu
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest
import pytest_asyncio
from fastapi import APIRouter as _APIRouter
from httpx import ASGITransport, AsyncClient

CLAIM_DIR = os.path.join(os.path.dirname(__file__), "..", "claim")


class FakeAioRpcError(grpc.aio.AioRpcError):
    def __init__(self, status_code: grpc.StatusCode, message: str):
        self._status_code = status_code
        self._message = message
        self._code = status_code
        self._details = message
        self._debug_error_string = ""

    def code(self):
        return self._status_code

    def details(self):
        return self._message


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def claim_client():
    # ── 1. Stub generated gRPC modules ──────────────────────────────────────
    sys.modules.setdefault("inventory_pb2", MagicMock())
    sys.modules.setdefault("inventory_pb2_grpc", MagicMock())

    if "claim_log_pb2" not in sys.modules:
        claim_log_pb2 = MagicMock()
        claim_log_pb2.PENDING_COLLECTION = 1
        claim_log_pb2.AWAITING_VENDOR_APPROVAL = 2
        claim_log_pb2.COMPLETED = 3
        claim_log_pb2.CANCELLED = 4

        class _ClaimStatus:
            @staticmethod
            def Name(value):
                return {
                    1: "PENDING_COLLECTION",
                    2: "AWAITING_VENDOR_APPROVAL",
                    3: "COMPLETED",
                    4: "CANCELLED",
                }.get(value, "CLAIM_STATUS_UNSPECIFIED")

        claim_log_pb2.ClaimStatus = _ClaimStatus
        sys.modules["claim_log_pb2"] = claim_log_pb2

    sys.modules.setdefault("claim_log_pb2_grpc", MagicMock())
    sys.modules.setdefault("verification_pb2", MagicMock())
    sys.modules.setdefault("verification_pb2_grpc", MagicMock())

    # ── 2. Mock waitlist modules before claim.py is loaded ──────────────────
    waitlist_db_mock = MagicMock()
    waitlist_db_mock.init_db = AsyncMock()
    sys.modules["waitlist_db"] = waitlist_db_mock

    waitlist_router_mock = MagicMock()
    waitlist_router_mock.router = _APIRouter()          # real empty router — safe for include_router
    waitlist_router_mock.try_promote_next = AsyncMock(return_value=(None, 5))
    sys.modules["waitlist_router"] = waitlist_router_mock

    # ── 3. Mock shared.jwt_auth ──────────────────────────────────────────────
    mock_jwt_fn = AsyncMock(return_value={"sub": "42"})
    shared_jwt_mock = MagicMock()
    shared_jwt_mock.verify_jwt_token = mock_jwt_fn
    sys.modules.setdefault("shared", MagicMock())
    sys.modules["shared.jwt_auth"] = shared_jwt_mock

    # ── 4. Load claim module ─────────────────────────────────────────────────
    spec = _ilu.spec_from_file_location("claim_app", os.path.join(CLAIM_DIR, "claim.py"))
    claim_mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(claim_mod)

    # ── 5. Override JWT dependency for all tests (default: sub=42) ──────────
    claim_mod.app.dependency_overrides[claim_mod.verify_jwt_token] = lambda: {"sub": "42"}

    # ── 6. Patch downstream clients ─────────────────────────────────────────
    with (
        patch.object(claim_mod, "_verify_claim_eligibility", new_callable=AsyncMock) as mock_verify,
        patch.object(claim_mod.inventory_client, "lock_listing_pending_collection", new_callable=AsyncMock) as mock_lock,
        patch.object(claim_mod.inventory_client, "rollback_listing_to_available", new_callable=AsyncMock) as mock_rollback,
        patch.object(claim_mod.claim_log_client, "create_claim_log", new_callable=AsyncMock) as mock_create_log,
        patch.object(claim_mod.claim_log_client, "get_claim_log", new_callable=AsyncMock) as mock_get_log,
        patch.object(claim_mod.claim_log_client, "update_claim_status", new_callable=AsyncMock) as mock_update_status,
        patch.object(claim_mod.publisher, "publish_claim_success", new_callable=AsyncMock) as mock_pub_success,
        patch.object(claim_mod.publisher, "publish_claim_failure", new_callable=AsyncMock) as mock_pub_failure,
        patch.object(claim_mod.publisher, "publish_claim_cancelled", new_callable=AsyncMock) as mock_pub_cancelled,
        patch.object(claim_mod, "try_promote_next", new_callable=AsyncMock) as mock_promote,
    ):
        mock_verify.return_value = None
        mock_lock.return_value = 4
        mock_rollback.return_value = 5
        mock_promote.return_value = (None, 5)

        mock_create_log.return_value = MagicMock(
            id=11, listing_id=1, charity_id=42, listing_version=4, status=1,
            created_at="2026-01-01T00:00:00Z", updated_at=None,
        )

        # Default get_claim_log response: claim owned by charity 42, PENDING_COLLECTION
        claim_log_record = MagicMock()
        claim_log_record.id = 10
        claim_log_record.listing_id = 1
        claim_log_record.charity_id = 42
        claim_log_record.listing_version = 3
        claim_log_record.status = 1   # claim_log_pb2.PENDING_COLLECTION
        mock_get_log.return_value = claim_log_record

        mock_update_status.return_value = MagicMock(
            success=True, claim_id=10, status=4, listing_id=1, listing_version=5,
        )

        async with AsyncClient(
            transport=ASGITransport(app=claim_mod.app),
            base_url="http://test",
        ) as client:
            yield {
                "client": client,
                "mod": claim_mod,
                "mock_verify": mock_verify,
                "mock_lock": mock_lock,
                "mock_rollback": mock_rollback,
                "mock_create_log": mock_create_log,
                "mock_get_log": mock_get_log,
                "mock_update_status": mock_update_status,
                "mock_pub_success": mock_pub_success,
                "mock_pub_failure": mock_pub_failure,
                "mock_pub_cancelled": mock_pub_cancelled,
                "mock_promote": mock_promote,
                "claim_log_record": claim_log_record,
            }


# ── Health ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(claim_client):
    response = await claim_client["client"].get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "claim"}


# ── POST /claims — happy path ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_claim_success(claim_client):
    payload = {"listing_id": 1, "charity_id": 42, "listing_version": 1}

    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING_COLLECTION"
    assert body["id"] == 11
    claim_client["mock_verify"].assert_called_once_with(42, 1)
    claim_client["mock_lock"].assert_called_once_with(listing_id=1, expected_version=1)
    claim_client["mock_pub_success"].assert_called_once()
    claim_client["mock_pub_failure"].assert_not_called()


# ── POST /claims — JWT guard ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_claim_jwt_mismatch_returns_403(claim_client):
    """JWT sub (42) does not match the charity_id in the body (99) → 403."""
    # Override JWT to return a different sub only for this test
    claim_client["mod"].app.dependency_overrides[
        claim_client["mod"].verify_jwt_token
    ] = lambda: {"sub": "99"}

    payload = {"listing_id": 1, "charity_id": 42, "listing_version": 1}
    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 403
    # Restore default override so subsequent tests are unaffected
    claim_client["mod"].app.dependency_overrides[
        claim_client["mod"].verify_jwt_token
    ] = lambda: {"sub": "42"}


# ── POST /claims — downstream errors ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_claim_listing_not_found(claim_client):
    claim_client["mock_lock"].side_effect = FakeAioRpcError(grpc.StatusCode.NOT_FOUND, "no listing")

    payload = {"listing_id": 999, "charity_id": 42, "listing_version": 0}
    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_claim_already_claimed(claim_client):
    claim_client["mock_lock"].side_effect = FakeAioRpcError(grpc.StatusCode.ABORTED, "version mismatch")

    payload = {"listing_id": 1, "charity_id": 42, "listing_version": 0}
    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_claim_inventory_unavailable(claim_client):
    claim_client["mock_lock"].side_effect = FakeAioRpcError(grpc.StatusCode.UNAVAILABLE, "down")

    payload = {"listing_id": 1, "charity_id": 42, "listing_version": 0}
    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_claim_log_timeout_triggers_compensation(claim_client):
    claim_client["mock_create_log"].side_effect = FakeAioRpcError(grpc.StatusCode.UNAVAILABLE, "down")

    payload = {"listing_id": 7, "charity_id": 42, "listing_version": 2}
    response = await claim_client["client"].post("/claims", json=payload)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "claim_log_unavailable"
    assert detail["inventory_rollback_succeeded"] is True
    claim_client["mock_rollback"].assert_called_once_with(7, 4)
    claim_client["mock_pub_failure"].assert_called_once()


# ── DELETE /claims/{id} — cancel claim ────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_claim_success(claim_client):
    """Happy path: PENDING_COLLECTION claim cancelled, waitlist empty → publish cancelled."""
    response = await claim_client["client"].request(
        "DELETE", "/claims/10", json={"charity_id": 42}
    )

    assert response.status_code == 204
    claim_client["mock_get_log"].assert_called_once_with(10)
    claim_client["mock_rollback"].assert_called_once_with(1, 3)     # listing_id=1, version=3
    claim_client["mock_update_status"].assert_called_once()
    claim_client["mock_promote"].assert_called_once_with(listing_id=1, available_version=5)
    claim_client["mock_pub_cancelled"].assert_called_once()         # queue empty → publish


@pytest.mark.asyncio
async def test_cancel_claim_promotes_waitlist_charity(claim_client):
    """When a waitlist charity is eligible, publish_claim_cancelled is NOT fired."""
    claim_client["mock_promote"].return_value = (99, 6)   # charity 99 promoted

    response = await claim_client["client"].request(
        "DELETE", "/claims/10", json={"charity_id": 42}
    )

    assert response.status_code == 204
    claim_client["mock_pub_cancelled"].assert_not_called()


@pytest.mark.asyncio
async def test_cancel_claim_wrong_owner_returns_403(claim_client):
    """Body charity_id doesn't match the claim's charity_id stored in Claim Log."""
    response = await claim_client["client"].request(
        "DELETE", "/claims/10", json={"charity_id": 999}   # mismatch: claim is owned by 42
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_cancel_claim_wrong_status_returns_409(claim_client):
    """Only PENDING_COLLECTION claims can be cancelled."""
    import claim_log_pb2
    claim_client["claim_log_record"].status = claim_log_pb2.COMPLETED   # already done

    response = await claim_client["client"].request(
        "DELETE", "/claims/10", json={"charity_id": 42}
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_cancel_claim_not_found_returns_404(claim_client):
    claim_client["mock_get_log"].side_effect = FakeAioRpcError(grpc.StatusCode.NOT_FOUND, "no claim")

    response = await claim_client["client"].request(
        "DELETE", "/claims/10", json={"charity_id": 42}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_claim_inventory_rollback_failure_returns_503(claim_client):
    claim_client["mock_rollback"].side_effect = FakeAioRpcError(grpc.StatusCode.UNAVAILABLE, "inv down")

    response = await claim_client["client"].request(
        "DELETE", "/claims/10", json={"charity_id": 42}
    )

    assert response.status_code == 503

