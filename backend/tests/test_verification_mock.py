"""
Tests for the Verification Service mock mode.

These tests verify the outsystems_client mock behaviour directly
without needing a live OutSystems environment or gRPC server.

Run with:
    MOCK_OUTSYSTEMS=true pytest backend/tests/test_verification_mock.py -v
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "outsystems_wrapper"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reload_client(mock: bool, approved: bool):
    """
    Reloads outsystems_client with fresh env vars.
    Required because MOCK_OUTSYSTEMS is read at module level.
    """
    import importlib
    os.environ["MOCK_OUTSYSTEMS"] = "true" if mock else "false"
    os.environ["MOCK_OUTSYSTEMS_APPROVED"] = "true" if approved else "false"

    if "outsystems_client" in sys.modules:
        del sys.modules["outsystems_client"]

    import outsystems_client
    return outsystems_client


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_approved():
    """
    Mock mode with MOCK_OUTSYSTEMS_APPROVED=true should return
    approved=True and empty rejection reason.
    """
    client = _reload_client(mock=True, approved=True)
    approved, reason = await client.check_charity_eligibility(
        charity_id=1,
        listing_id=1,
    )
    assert approved is True
    assert reason == ""


@pytest.mark.asyncio
async def test_mock_rejected():
    """
    Mock mode with MOCK_OUTSYSTEMS_APPROVED=false should return
    approved=False and rejection reason MISSING_WAIVER.
    """
    client = _reload_client(mock=True, approved=False)
    approved, reason = await client.check_charity_eligibility(
        charity_id=1,
        listing_id=1,
    )
    assert approved is False
    assert reason == "MISSING_WAIVER"


@pytest.mark.asyncio
async def test_mock_does_not_call_outsystems(monkeypatch):
    """
    Mock mode should never make an HTTP call to OutSystems.
    Verifies that httpx.AsyncClient is never instantiated.
    """
    import httpx
    client = _reload_client(mock=True, approved=True)

    call_count = 0

    class FakeClient:
        async def __aenter__(self):
            nonlocal call_count
            call_count += 1
            return self
        async def __aexit__(self, *args): pass

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())

    await client.check_charity_eligibility(charity_id=1, listing_id=1)
    assert call_count == 0, "Mock mode should not call OutSystems"


@pytest.mark.skipif(
    os.getenv("MOCK_OUTSYSTEMS", "true").lower() == "true",
    reason="Skipped in mock mode — needs live OutSystems"
)
@pytest.mark.asyncio
async def test_real_outsystems_reachable():
    """
    Real mode smoke test — only runs when MOCK_OUTSYSTEMS=false.
    Verifies OutSystems endpoint is reachable and returns a valid response.
    """
    client = _reload_client(mock=False, approved=True)
    try:
        approved, reason = await client.check_charity_eligibility(
            charity_id=1,
            listing_id=1,
        )
        assert isinstance(approved, bool)
        assert isinstance(reason, str)
    except client.OutSystemsVerificationError as exc:
        pytest.fail(f"OutSystems unreachable: {exc}")