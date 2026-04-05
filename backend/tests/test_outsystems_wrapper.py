"""
OutSystems Wrapper tests — all 3 login endpoints in MOCK mode.

MOCK_OUTSYSTEMS=true is set before the module loads so no real OutSystems or
gRPC calls are made. This covers:
  - /health
  - POST /auth/charity/login
  - POST /auth/vendor/login
  - POST /auth/public/login
  - 400 validation when required fields are missing
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
