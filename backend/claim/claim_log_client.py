"""
Thin async gRPC client for Claim Log operations.
Used by claim orchestrator create + handshake endpoints.
"""
import os

import grpc
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

CLAIM_LOG_GRPC_HOST = os.getenv("CLAIM_LOG_GRPC_HOST", "localhost")
CLAIM_LOG_GRPC_PORT = os.getenv("CLAIM_LOG_GRPC_PORT", "50061")
CLAIM_LOG_GRPC_ADDR = f"{CLAIM_LOG_GRPC_HOST}:{CLAIM_LOG_GRPC_PORT}"


async def create_claim_log(listing_id: int, charity_id: int, listing_version: int, status: int):
    import claim_log_pb2
    import claim_log_pb2_grpc

    async with grpc.aio.insecure_channel(CLAIM_LOG_GRPC_ADDR) as channel:
        stub = claim_log_pb2_grpc.ClaimLogServiceStub(channel)
        return await stub.CreateClaimLog(
            claim_log_pb2.CreateClaimLogRequest(
                listing_id=listing_id,
                charity_id=charity_id,
                listing_version=listing_version,
                status=status,
            )
        )


async def get_claim_log(claim_id: int):
    """Fetch a single claim record by ID.  Returns GetClaimLogResponse (includes charity_id)."""
    import claim_log_pb2
    import claim_log_pb2_grpc

    async with grpc.aio.insecure_channel(CLAIM_LOG_GRPC_ADDR) as channel:
        stub = claim_log_pb2_grpc.ClaimLogServiceStub(channel)
        return await stub.GetClaimLog(
            claim_log_pb2.GetClaimLogRequest(claim_id=claim_id)
        )


async def update_claim_status(claim_id: int, new_status: int):
    # Local import keeps tests decoupled from generated stubs.
    import claim_log_pb2
    import claim_log_pb2_grpc

    async with grpc.aio.insecure_channel(CLAIM_LOG_GRPC_ADDR) as channel:
        stub = claim_log_pb2_grpc.ClaimLogServiceStub(channel)
        return await stub.UpdateClaimStatus(
            claim_log_pb2.UpdateClaimStatusRequest(
                claim_id=claim_id,
                new_status=new_status,
            )
        )


def map_claim_log_grpc_error(exc: grpc.aio.AioRpcError) -> HTTPException:
    code = exc.code()
    if code == grpc.StatusCode.NOT_FOUND:
        return HTTPException(status_code=404, detail="Claim not found")
    if code == grpc.StatusCode.INVALID_ARGUMENT:
        return HTTPException(status_code=400, detail="Invalid claim status update request")
    if code == grpc.StatusCode.ABORTED:
        return HTTPException(status_code=409, detail="Invalid claim status transition")
    return HTTPException(status_code=503, detail="Claim Log service unavailable")
