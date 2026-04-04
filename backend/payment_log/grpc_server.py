import os

import grpc
import grpc.aio
from sqlalchemy import select

import payment_log_pb2
import payment_log_pb2_grpc
from database import SessionLocal
from models import PaymentRecord, PaymentStatus

GRPC_PORT = int(os.getenv("PAYMENT_LOG_GRPC_PORT", "50062"))

_STATUS_MAP = {
    payment_log_pb2.PENDING: PaymentStatus.PENDING,
    payment_log_pb2.SUCCESS: PaymentStatus.SUCCESS,
    payment_log_pb2.COLLECTED: PaymentStatus.COLLECTED,
    payment_log_pb2.REFUNDED: PaymentStatus.REFUNDED,
    payment_log_pb2.FAILED: PaymentStatus.FAILED,
    payment_log_pb2.FORFEITED: PaymentStatus.FORFEITED,
}

_REVERSE_STATUS_MAP = {
    PaymentStatus.PENDING: payment_log_pb2.PENDING,
    PaymentStatus.SUCCESS: payment_log_pb2.SUCCESS,
    PaymentStatus.COLLECTED: payment_log_pb2.COLLECTED,
    PaymentStatus.REFUNDED: payment_log_pb2.REFUNDED,
    PaymentStatus.FAILED: payment_log_pb2.FAILED,
    PaymentStatus.FORFEITED: payment_log_pb2.FORFEITED,
}

_ALLOWED_TRANSITIONS = {
    PaymentStatus.PENDING: {PaymentStatus.SUCCESS, PaymentStatus.REFUNDED, PaymentStatus.FAILED},
    PaymentStatus.SUCCESS: {PaymentStatus.COLLECTED, PaymentStatus.REFUNDED, PaymentStatus.FORFEITED},
    PaymentStatus.COLLECTED: set(),
    PaymentStatus.REFUNDED: set(),
    PaymentStatus.FAILED: set(),
    PaymentStatus.FORFEITED: set(),
}


async def _get_record_or_abort(db, context, transaction_id: str):
    record = await db.scalar(
        select(PaymentRecord).where(
            PaymentRecord.stripe_transaction_id == transaction_id
        )
    )
    if record is None:
        await context.abort(
            grpc.StatusCode.NOT_FOUND,
            f"Payment transaction {transaction_id} not found",
        )
        return None
    return record


class PaymentLogServicer(payment_log_pb2_grpc.PaymentLogServiceServicer):
    async def CreatePaymentLog(self, request, context):
        async with SessionLocal() as db:
            existing = await db.scalar(
                select(PaymentRecord).where(
                    PaymentRecord.stripe_transaction_id == request.transaction_id
                )
            )
            if existing is not None:
                await context.abort(
                    grpc.StatusCode.ALREADY_EXISTS,
                    f"Payment transaction {request.transaction_id} already exists",
                )
                return payment_log_pb2.CreatePaymentLogResponse()

            record = PaymentRecord(
                stripe_transaction_id=request.transaction_id,
                listing_id=request.listing_id,
                listing_version=request.listing_version,
                amount=request.amount,
                status=PaymentStatus.PENDING,
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)

            return payment_log_pb2.CreatePaymentLogResponse(
                success=True,
                transaction_id=record.stripe_transaction_id,
                status=_REVERSE_STATUS_MAP[record.status],
                listing_id=record.listing_id,
                listing_version=record.listing_version,
                amount=record.amount,
            )

    async def GetPaymentLog(self, request, context):
        async with SessionLocal() as db:
            record = await _get_record_or_abort(db, context, request.transaction_id)
            if record is None:
                return payment_log_pb2.GetPaymentLogResponse()

            return payment_log_pb2.GetPaymentLogResponse(
                found=True,
                transaction_id=record.stripe_transaction_id,
                status=_REVERSE_STATUS_MAP[record.status],
                listing_id=record.listing_id,
                listing_version=record.listing_version,
                amount=record.amount,
                created_at=record.created_at.isoformat() if record.created_at else "",
                updated_at=record.updated_at.isoformat() if record.updated_at else "",
            )

    async def UpdatePaymentStatus(self, request, context):
        new_status = _STATUS_MAP.get(request.new_status)
        if new_status is None:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid payment status")
            return payment_log_pb2.UpdatePaymentStatusResponse()

        async with SessionLocal() as db:
            record = await _get_record_or_abort(db, context, request.transaction_id)
            if record is None:
                return payment_log_pb2.UpdatePaymentStatusResponse()

            if record.status != new_status and new_status not in _ALLOWED_TRANSITIONS[record.status]:
                await context.abort(
                    grpc.StatusCode.ABORTED,
                    f"Invalid transition from {record.status} to {new_status}",
                )
                return payment_log_pb2.UpdatePaymentStatusResponse()

            record.status = new_status
            if request.use_listing_version:
                record.listing_version = request.listing_version
            await db.commit()
            await db.refresh(record)

            return payment_log_pb2.UpdatePaymentStatusResponse(
                success=True,
                transaction_id=record.stripe_transaction_id,
                status=_REVERSE_STATUS_MAP[record.status],
                listing_id=record.listing_id,
                listing_version=record.listing_version,
                amount=record.amount,
            )


async def start_grpc_server() -> grpc.aio.Server:
    server = grpc.aio.server()
    payment_log_pb2_grpc.add_PaymentLogServiceServicer_to_server(PaymentLogServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    await server.start()
    print(f"Payment Log gRPC server listening on port {GRPC_PORT}")
    return server
