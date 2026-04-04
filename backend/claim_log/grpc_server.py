import os

import grpc
import grpc.aio

import claim_log_pb2
import claim_log_pb2_grpc
from database import SessionLocal
from models import ClaimRecord, ClaimStatus

GRPC_PORT = int(os.getenv("CLAIM_LOG_GRPC_PORT", "50061"))

_STATUS_MAP = {
    claim_log_pb2.PENDING_COLLECTION: ClaimStatus.PENDING_COLLECTION,
    claim_log_pb2.AWAITING_VENDOR_APPROVAL: ClaimStatus.AWAITING_VENDOR_APPROVAL,
    claim_log_pb2.COMPLETED: ClaimStatus.COMPLETED,
    claim_log_pb2.CANCELLED: ClaimStatus.CANCELLED,
}

_REVERSE_STATUS_MAP = {
    ClaimStatus.PENDING_COLLECTION: claim_log_pb2.PENDING_COLLECTION,
    ClaimStatus.AWAITING_VENDOR_APPROVAL: claim_log_pb2.AWAITING_VENDOR_APPROVAL,
    ClaimStatus.COMPLETED: claim_log_pb2.COMPLETED,
    ClaimStatus.CANCELLED: claim_log_pb2.CANCELLED,
}

_ALLOWED_TRANSITIONS = {
    ClaimStatus.PENDING_COLLECTION: {
        ClaimStatus.AWAITING_VENDOR_APPROVAL,
        ClaimStatus.COMPLETED,
        ClaimStatus.CANCELLED,
    },
    ClaimStatus.AWAITING_VENDOR_APPROVAL: {
        ClaimStatus.COMPLETED,
        ClaimStatus.CANCELLED,
    },
    ClaimStatus.COMPLETED: set(),
    ClaimStatus.CANCELLED: set(),
}


class ClaimLogServicer(claim_log_pb2_grpc.ClaimLogServiceServicer):
    async def CreateClaimLog(self, request, context):
        status = _STATUS_MAP.get(request.status)
        if status is None:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid claim status")
            return claim_log_pb2.CreateClaimLogResponse()

        if request.listing_id <= 0 or request.charity_id <= 0 or request.listing_version < 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid claim create payload")
            return claim_log_pb2.CreateClaimLogResponse()

        async with SessionLocal() as db:
            record = ClaimRecord(
                listing_id=request.listing_id,
                charity_id=request.charity_id,
                listing_version=request.listing_version,
                status=status,
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)

            return claim_log_pb2.CreateClaimLogResponse(
                id=record.id,
                listing_id=record.listing_id,
                charity_id=record.charity_id,
                listing_version=record.listing_version,
                status=_REVERSE_STATUS_MAP[record.status],
            )

    async def GetClaimLog(self, request, context):
        async with SessionLocal() as db:
            record = await db.get(ClaimRecord, request.claim_id)
            if record is None:
                await context.abort(
                    grpc.StatusCode.NOT_FOUND,
                    f"Claim {request.claim_id} not found",
                )
                return claim_log_pb2.GetClaimLogResponse()

            return claim_log_pb2.GetClaimLogResponse(
                id=record.id,
                listing_id=record.listing_id,
                charity_id=record.charity_id,
                listing_version=record.listing_version,
                status=_REVERSE_STATUS_MAP[record.status],
                created_at=record.created_at.isoformat() if record.created_at else "",
            )

    async def UpdateClaimStatus(self, request, context):
        new_status = _STATUS_MAP.get(request.new_status)
        if new_status is None:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid claim status")
            return claim_log_pb2.UpdateClaimStatusResponse()

        async with SessionLocal() as db:
            record = await db.get(ClaimRecord, request.claim_id)
            if record is None:
                await context.abort(grpc.StatusCode.NOT_FOUND, f"Claim {request.claim_id} not found")
                return claim_log_pb2.UpdateClaimStatusResponse()

            if record.status != new_status and new_status not in _ALLOWED_TRANSITIONS[record.status]:
                await context.abort(
                    grpc.StatusCode.ABORTED,
                    f"Invalid transition from {record.status} to {new_status}",
                )
                return claim_log_pb2.UpdateClaimStatusResponse()

            record.status = new_status
            await db.commit()
            await db.refresh(record)

            return claim_log_pb2.UpdateClaimStatusResponse(
                success=True,
                claim_id=record.id,
                status=_REVERSE_STATUS_MAP[record.status],
                listing_id=record.listing_id,
                listing_version=record.listing_version,
            )


async def start_grpc_server() -> grpc.aio.Server:
    server = grpc.aio.server()
    claim_log_pb2_grpc.add_ClaimLogServiceServicer_to_server(ClaimLogServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    await server.start()
    print(f"Claim Log gRPC server listening on port {GRPC_PORT}")
    return server
