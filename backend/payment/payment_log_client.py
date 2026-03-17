"""
Thin async gRPC client for Payment Log status updates.
Used by manual approve/reject endpoints in payment orchestrator.
"""
import os

import grpc
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

PAYMENT_LOG_GRPC_HOST = os.getenv("PAYMENT_LOG_GRPC_HOST", "localhost")
PAYMENT_LOG_GRPC_PORT = os.getenv("PAYMENT_LOG_GRPC_PORT", "50062")
PAYMENT_LOG_GRPC_ADDR = f"{PAYMENT_LOG_GRPC_HOST}:{PAYMENT_LOG_GRPC_PORT}"


async def update_payment_status(transaction_id: str, new_status: int):
    # Local import keeps tests decoupled from generated stubs.
    import payment_log_pb2
    import payment_log_pb2_grpc

    async with grpc.aio.insecure_channel(PAYMENT_LOG_GRPC_ADDR) as channel:
        stub = payment_log_pb2_grpc.PaymentLogServiceStub(channel)
        return await stub.UpdatePaymentStatus(
            payment_log_pb2.UpdatePaymentStatusRequest(
                transaction_id=transaction_id,
                new_status=new_status,
            )
        )


def map_payment_log_grpc_error(exc: grpc.aio.AioRpcError) -> HTTPException:
    code = exc.code()
    if code == grpc.StatusCode.NOT_FOUND:
        return HTTPException(status_code=404, detail="Payment transaction not found")
    if code == grpc.StatusCode.INVALID_ARGUMENT:
        return HTTPException(status_code=400, detail="Invalid payment status update request")
    if code == grpc.StatusCode.ABORTED:
        return HTTPException(status_code=409, detail="Invalid payment status transition")
    return HTTPException(status_code=503, detail="Payment Log service unavailable")
