"""
Unit tests for the Stripe Wrapper service.

All Stripe SDK calls and downstream HTTP are mocked — no real network calls.

Run:
    pytest backend/tests/test_stripe_wrapper.py -v
"""
import importlib.util as ilu
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

STRIPE_WRAPPER_DIR = os.path.join(os.path.dirname(__file__), "..", "stripe_wrapper")


def _load_app(monkeypatch, webhook_secret="whsec_test"):
    """Load a fresh stripe_wrapper module instance with mocked env + Stripe SDK."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", webhook_secret)
    monkeypatch.setenv("PAYMENT_SERVICE_URL", "http://payment-service:8003")

    # Provide a fully-mocked stripe module so no real SDK code runs.
    stripe_mock = MagicMock()
    stripe_mock.api_key = None
    stripe_mock.error = MagicMock()
    stripe_mock.error.StripeError = Exception
    stripe_mock.error.SignatureVerificationError = type("SigError", (Exception,), {})
    sys.modules["stripe"] = stripe_mock

    # Load module fresh (bypasses any cached import).
    module_name = f"stripe_wrapper_{webhook_secret[:8]}"
    spec = ilu.spec_from_file_location(
        module_name,
        os.path.join(STRIPE_WRAPPER_DIR, "stripe_wrapper.py"),
    )
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Inject the mock into the loaded module so our patches work.
    mod.stripe = stripe_mock
    return mod.app, stripe_mock, mod


# ── Health ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(monkeypatch):
    app, _, _mod = _load_app(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


# ── POST /stripe/intent ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_intent_success(monkeypatch):
    """Happy path — PaymentIntent created, correct response shape returned."""
    app, stripe_mock, _ = _load_app(monkeypatch)
    stripe_mock.PaymentIntent.create.return_value = SimpleNamespace(
        id="pi_test_abc",
        client_secret="pi_test_abc_secret_xyz",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/stripe/intent", json={"listing_id": 5, "amount": 12.50})

    assert resp.status_code == 201
    body = resp.json()
    assert body["payment_intent_id"] == "pi_test_abc"
    assert body["client_secret"] == "pi_test_abc_secret_xyz"


@pytest.mark.asyncio
async def test_create_intent_converts_amount_to_cents(monkeypatch):
    """Amount in dollars must be converted to integer cents for Stripe."""
    app, stripe_mock, _ = _load_app(monkeypatch)
    stripe_mock.PaymentIntent.create.return_value = SimpleNamespace(
        id="pi_x", client_secret="pi_x_secret_y"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/stripe/intent", json={"listing_id": 1, "amount": 9.99})

    _, kwargs = stripe_mock.PaymentIntent.create.call_args
    # 9.99 * 100 rounded = 999, not 998 (int truncation bug)
    assert kwargs["amount"] == 999


@pytest.mark.asyncio
async def test_create_intent_sets_sgd_currency(monkeypatch):
    """Currency must always be 'sgd'."""
    app, stripe_mock, _ = _load_app(monkeypatch)
    stripe_mock.PaymentIntent.create.return_value = SimpleNamespace(
        id="pi_y", client_secret="pi_y_secret_z"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/stripe/intent", json={"listing_id": 2, "amount": 5.00})

    _, kwargs = stripe_mock.PaymentIntent.create.call_args
    assert kwargs["currency"] == "sgd"
    assert kwargs["metadata"] == {"listing_id": 2}


@pytest.mark.asyncio
async def test_create_intent_stripe_error_returns_502(monkeypatch):
    """Stripe SDK raises StripeError → wrapper must return 502, not 500."""
    app, stripe_mock, _ = _load_app(monkeypatch)
    stripe_mock.PaymentIntent.create.side_effect = Exception("card_declined")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/stripe/intent", json={"listing_id": 3, "amount": 10.00})

    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_create_intent_invalid_amount_rejected(monkeypatch):
    """Amount <= 0 must be rejected by Pydantic validation with 422."""
    app, _, _mod = _load_app(monkeypatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/stripe/intent", json={"listing_id": 1, "amount": 0})

    assert resp.status_code == 422


# ── POST /stripe/refund ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_issue_refund_success(monkeypatch):
    """Happy path — refund issued, correct response shape returned."""
    app, stripe_mock, _ = _load_app(monkeypatch)
    stripe_mock.Refund.create.return_value = SimpleNamespace(
        id="re_test_123",
        status="succeeded",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/stripe/refund",
            json={"payment_intent_id": "pi_test_abc", "amount": 12.50},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["refund_id"] == "re_test_123"
    assert body["status"] == "succeeded"


@pytest.mark.asyncio
async def test_issue_refund_uses_correct_payment_intent_id(monkeypatch):
    """Refund must be issued against the provided payment_intent_id."""
    app, stripe_mock, _ = _load_app(monkeypatch)
    stripe_mock.Refund.create.return_value = SimpleNamespace(id="re_x", status="succeeded")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post(
            "/stripe/refund",
            json={"payment_intent_id": "pi_specific_id", "amount": 5.00},
        )

    stripe_mock.Refund.create.assert_called_once_with(payment_intent="pi_specific_id")


@pytest.mark.asyncio
async def test_issue_refund_stripe_error_returns_502(monkeypatch):
    """Stripe SDK raises on refund → wrapper must return 502."""
    app, stripe_mock, _ = _load_app(monkeypatch)
    stripe_mock.Refund.create.side_effect = Exception("refund_failed")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/stripe/refund",
            json={"payment_intent_id": "pi_test_abc", "amount": 12.50},
        )

    assert resp.status_code == 502


# ── POST /stripe/webhook ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_400(monkeypatch):
    """Tampered or missing Stripe-Signature → 400."""
    app, stripe_mock, _ = _load_app(monkeypatch)
    stripe_mock.Webhook.construct_event.side_effect = (
        stripe_mock.error.SignatureVerificationError("bad sig")
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/stripe/webhook",
            content=b'{"type":"payment_intent.succeeded"}',
            headers={"stripe-signature": "t=1,v1=bad"},
        )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_missing_secret_returns_500(monkeypatch):
    """If STRIPE_WEBHOOK_SECRET is empty, webhook must refuse with 500."""
    app, _, _mod = _load_app(monkeypatch, webhook_secret="")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/stripe/webhook",
            content=b'{"type":"payment_intent.succeeded"}',
            headers={"stripe-signature": "t=1,v1=abc"},
        )

    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_webhook_unrelated_event_ignored(monkeypatch):
    """Non-payment events are acknowledged with 200 and not forwarded."""
    app, stripe_mock, _ = _load_app(monkeypatch)
    stripe_mock.Webhook.construct_event.return_value = {
        "type": "customer.created",
        "data": {"object": {}},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/stripe/webhook",
            content=b'{"type":"customer.created"}',
            headers={"stripe-signature": "t=1,v1=abc"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"received": True}


@pytest.mark.asyncio
async def test_webhook_payment_intent_succeeded_forwards_correct_payload(monkeypatch):
    """
    payment_intent.succeeded must forward { stripe_transaction_id, amount }
    to the payment service with amount converted from cents to dollars.
    """
    app, stripe_mock, mod = _load_app(monkeypatch)
    stripe_mock.Webhook.construct_event.return_value = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_live_999",
                "amount_received": 1250,   # SGD $12.50 in cents
            },
        },
    }

    # Inject a mock httpx into the loaded module so only the module's calls are intercepted.
    captured = {}
    mock_http_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_httpx.HTTPStatusError = __import__("httpx").HTTPStatusError
    mod.httpx = mock_httpx

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/stripe/webhook",
            content=b'{"type":"payment_intent.succeeded"}',
            headers={"stripe-signature": "t=1,v1=abc"},
        )

    assert resp.status_code == 200
    assert resp.json()["received"] is True

    mock_http_client.post.assert_called_once()
    _, kwargs = mock_http_client.post.call_args
    forwarded = kwargs["json"]
    assert forwarded["stripe_transaction_id"] == "pi_live_999"
    assert abs(forwarded["amount"] - 12.50) < 1e-9   # cents / 100 = dollars


@pytest.mark.asyncio
async def test_webhook_payment_service_failure_returns_502(monkeypatch):
    """If the payment service rejects the forwarded webhook, wrapper returns 502."""
    app, stripe_mock, mod = _load_app(monkeypatch)
    stripe_mock.Webhook.construct_event.return_value = {
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_x", "amount_received": 500}},
    }

    import httpx as real_httpx

    mock_http_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = real_httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )
    mock_http_client.post = AsyncMock(return_value=mock_response)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_httpx.HTTPStatusError = real_httpx.HTTPStatusError
    mod.httpx = mock_httpx

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/stripe/webhook",
            content=b'{"type":"payment_intent.succeeded"}',
            headers={"stripe-signature": "t=1,v1=abc"},
        )

    assert resp.status_code == 502
