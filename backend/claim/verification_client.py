# claim-service/verification_client.py
import os
import grpc

from verification_pb2 import VerifyRequest          # generated from proto
from verification_pb2_grpc import VerificationStub  # generated from proto

VERIFICATION_GRPC_HOST = os.getenv("VERIFICATION_GRPC_HOST", "verification")
VERIFICATION_GRPC_PORT = os.getenv("VERIFICATION_GRPC_PORT", "50052")
VERIFICATION_GRPC_ADDR = f"{VERIFICATION_GRPC_HOST}:{VERIFICATION_GRPC_PORT}"


async def verify_charity_eligibility(charity_id: int) -> tuple[bool, str]:
    """
    Calls Verification Service over gRPC to check:
    - legal status
    - indemnity
    - anti-hoarding quota (daily limit)
    Returns (valid, reason).
    """
    async with grpc.aio.insecure_channel(VERIFICATION_GRPC_ADDR) as channel:
        stub = VerificationStub(channel)
        resp = await stub.VerifyCharity(VerifyRequest(charity_id=charity_id))
        return resp.valid, resp.reason
