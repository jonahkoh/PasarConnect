"""
Thin async gRPC client for Claim Log status updates.
Used by handshake endpoints in claim orchestrator.
"""
import os

import grpc
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

CLAIM_LOG_GRPC_HOST = os.getenv("CLAIM_LOG_GRPC_HOST", "localhost")
CLAIM_LOG_GRPC_PORT = os.getenv("CLAIM_LOG_GRPC_PORT", "50061")
CLAIM_LOG_GRPC_ADDR = f"{CLAIM_LOG_GRPC_HOST}:{CLAIM_LOG_GRPC_PORT}"


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
