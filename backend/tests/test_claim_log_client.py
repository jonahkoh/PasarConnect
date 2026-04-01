"""
Unit tests for claim_log_client.py.
These tests validate gRPC error mapping and request wiring independently
from claim.py route handlers.
"""

import importlib.util as _ilu
import os
import sys
from types import SimpleNamespace

import grpc
import pytest

CLAIM_DIR = os.path.join(os.path.dirname(__file__), "..", "claim")
_spec = _ilu.spec_from_file_location("claim_log_client", os.path.join(CLAIM_DIR, "claim_log_client.py"))
claim_log_client = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(claim_log_client)


class FakeAioRpcError(grpc.aio.AioRpcError):
    def __init__(self, status_code: grpc.StatusCode):
        self._status_code = status_code

    def code(self):
        return self._status_code

    def details(self):
        return "fake"


def test_map_claim_log_grpc_error_not_found():
    exc = FakeAioRpcError(grpc.StatusCode.NOT_FOUND)
    http_exc = claim_log_client.map_claim_log_grpc_error(exc)
    assert http_exc.status_code == 404
    assert http_exc.detail == "Claim not found"


def test_map_claim_log_grpc_error_invalid_argument():
    exc = FakeAioRpcError(grpc.StatusCode.INVALID_ARGUMENT)
    http_exc = claim_log_client.map_claim_log_grpc_error(exc)
    assert http_exc.status_code == 400
    assert http_exc.detail == "Invalid claim status update request"


def test_map_claim_log_grpc_error_aborted():
    exc = FakeAioRpcError(grpc.StatusCode.ABORTED)
    http_exc = claim_log_client.map_claim_log_grpc_error(exc)
    assert http_exc.status_code == 409
    assert http_exc.detail == "Invalid claim status transition"


def test_map_claim_log_grpc_error_fallback_503():
    exc = FakeAioRpcError(grpc.StatusCode.UNAVAILABLE)
    http_exc = claim_log_client.map_claim_log_grpc_error(exc)
    assert http_exc.status_code == 503
    assert http_exc.detail == "Claim Log service unavailable"


@pytest.mark.asyncio
async def test_update_claim_status_wires_request_and_stub_call(monkeypatch):
    captured = {
        "addr": None,
        "request": None,
        "channel_used": None,
    }

    class FakeChannel:
        def __init__(self, addr):
            captured["addr"] = addr

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeStub:
        def __init__(self, channel):
            captured["channel_used"] = channel

        async def UpdateClaimStatus(self, request):
            captured["request"] = request
            return SimpleNamespace(success=True, claim_id=99)

    def fake_request_factory(claim_id, new_status):
        return SimpleNamespace(claim_id=claim_id, new_status=new_status)

    fake_pb2 = SimpleNamespace(UpdateClaimStatusRequest=fake_request_factory)
    fake_pb2_grpc = SimpleNamespace(ClaimLogServiceStub=FakeStub)

    monkeypatch.setitem(sys.modules, "claim_log_pb2", fake_pb2)
    monkeypatch.setitem(sys.modules, "claim_log_pb2_grpc", fake_pb2_grpc)
    monkeypatch.setattr(claim_log_client.grpc.aio, "insecure_channel", FakeChannel)

    result = await claim_log_client.update_claim_status(claim_id=42, new_status=3)

    assert captured["addr"] == claim_log_client.CLAIM_LOG_GRPC_ADDR
    assert captured["channel_used"] is not None
    assert captured["request"].claim_id == 42
    assert captured["request"].new_status == 3
    assert result.success is True
    assert result.claim_id == 99
