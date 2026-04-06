"""
OutSystems Wrapper tests — all endpoints in MOCK mode.

MOCK_OUTSYSTEMS=true is set before the module loads so no real OutSystems or
gRPC calls are made. This covers:
  - /health
  - POST /auth/charity/login, /auth/vendor/login, /auth/public/login
  - POST /auth/public/register, /auth/charity/register, /auth/vendor/register
  - POST /admin/charity/approve, /admin/charity/reject
  - POST /admin/vendor/approve, /admin/vendor/reject
  - 422 validation when required fields are missing
"""

import importlib.util as _ilu
import os
import sys

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

WRAPPER_DIR = os.path.join(os.path.dirname(__file__), "..", "outsystems_wrapper")


@pytest_asyncio.fixture()
async def wrapper_client():
    # Force mock mode before the module reads its env vars at import time.
    os.environ["MOCK_OUTSYSTEMS"] = "true"

    # Stub gRPC proto modules — not needed in mock mode but imported at module level.
    sys.modules.setdefault("verification_pb2", __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock())
    sys.modules.setdefault("verification_pb2_grpc", __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock())

    spec = _ilu.spec_from_file_location("outsystems_app", os.path.join(WRAPPER_DIR, "outsystems_wrapper.py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    client = AsyncClient(transport=ASGITransport(app=mod.app), base_url="http://test")
    try:
        yield client
    finally:
        await client.aclose()


# ── /health ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(wrapper_client):
    response = await wrapper_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "outsystems"}


@pytest.mark.asyncio
async def test_auth_health_alias(wrapper_client):
    """Kong forwards /auth/health here with strip_path:false — the alias must respond."""
    response = await wrapper_client.get("/auth/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "outsystems"}


# ── Charity login ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_charity_login_mock_returns_correct_fields(wrapper_client):
    payload = {"email": "charity@example.com", "password": "pass123"}
    response = await wrapper_client.post("/auth/charity/login", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "mock.charity.token"
    assert body["token_type"] == "bearer"
    assert body["user_id"] == 1
    assert body["role"] == "charity"
    # status dict must be present and have the expected keys
    assert body["status"] is not None
    assert body["status"]["is_banned"] is False
    assert "claimed_today" in body["status"]


@pytest.mark.asyncio
async def test_charity_login_missing_password_returns_422(wrapper_client):
    response = await wrapper_client.post("/auth/charity/login", json={"email": "x@x.com"})
    assert response.status_code == 422


# ── Vendor login ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vendor_login_mock_returns_correct_fields(wrapper_client):
    payload = {"email": "vendor@example.com", "password": "pass123"}
    response = await wrapper_client.post("/auth/vendor/login", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "mock.vendor.token"
    assert body["token_type"] == "bearer"
    assert body["user_id"] == 1
    assert body["role"] == "vendor"
    # status dict must be present and have the expected keys
    assert body["status"] is not None
    assert body["status"]["is_compliant"] is True
    assert "license_expires_at" in body["status"]


@pytest.mark.asyncio
async def test_vendor_login_missing_email_returns_422(wrapper_client):
    response = await wrapper_client.post("/auth/vendor/login", json={"password": "pass"})
    assert response.status_code == 422


# ── Public login ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_public_login_mock_returns_correct_fields(wrapper_client):
    payload = {"email": "user@example.com", "password": "pass123"}
    response = await wrapper_client.post("/auth/public/login", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "mock.public.token"
    assert body["token_type"] == "bearer"
    assert body["user_id"] == 1
    assert body["role"] == "public"
    # Public login has no status field
    assert "status" not in body


@pytest.mark.asyncio
async def test_public_login_missing_fields_returns_422(wrapper_client):
    response = await wrapper_client.post("/auth/public/login", json={})
    assert response.status_code == 422


# ── Register endpoints ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_public_register_mock_returns_201(wrapper_client):
    payload = {"FullName": "John Doe", "Email": "john@example.com", "Password": "pass", "Phone": "91234567"}
    response = await wrapper_client.post("/auth/public/register", json=payload)
    assert response.status_code == 201
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_charity_register_mock_returns_201(wrapper_client):
    payload = {
        "FullName": "Jane Doe", "Email": "charity@example.com", "Password": "pass",
        "OrgName": "Food For All", "CharityRegNumber": "ROS1234567",
    }
    response = await wrapper_client.post("/auth/charity/register", json=payload)
    assert response.status_code == 201
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_vendor_register_mock_returns_201(wrapper_client):
    payload = {
        "FullName": "Bob Smith", "Email": "vendor@example.com", "Password": "pass",
        "BusinessName": "Bob's Bakery", "NeaLicenceNumber": "NEA123456",
        "LicenceExpiry": "2027-01-01", "Address": "123 Orchard Road", "Uen": "UEN123456",
    }
    response = await wrapper_client.post("/auth/vendor/register", json=payload)
    assert response.status_code == 201
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_public_register_missing_field_returns_422(wrapper_client):
    # Missing Phone
    payload = {"FullName": "John Doe", "Email": "john@example.com", "Password": "pass"}
    response = await wrapper_client.post("/auth/public/register", json=payload)
    assert response.status_code == 422


# ── Admin endpoints ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_approve_charity_mock(wrapper_client):
    response = await wrapper_client.post("/admin/charity/approve", json={"UserId": 7, "RejectionReason": ""})
    assert response.status_code == 200
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_admin_reject_charity_mock(wrapper_client):
    response = await wrapper_client.post("/admin/charity/reject", json={"UserId": 7, "RejectionReason": "Invalid number"})
    assert response.status_code == 200
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_admin_approve_vendor_mock(wrapper_client):
    response = await wrapper_client.post("/admin/vendor/approve", json={"UserId": 8, "RejectionReason": ""})
    assert response.status_code == 200
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_admin_reject_vendor_mock(wrapper_client):
    response = await wrapper_client.post("/admin/vendor/reject", json={"UserId": 8, "RejectionReason": "NEA licence expired"})
    assert response.status_code == 200
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_admin_action_missing_user_id_returns_422(wrapper_client):
    response = await wrapper_client.post("/admin/charity/approve", json={"RejectionReason": ""})
    assert response.status_code == 422
