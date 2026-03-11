import grpc
import grpc.aio

import inventory_pb2
import inventory_pb2_grpc
from database import SessionLocal
from lock_service import LockConflictError, ListingNotFoundError, lock_listing
from models import ListingStatus

GRPC_PORT = 50051

# Map the proto enum integers to our SQLAlchemy enum values
_STATUS_MAP = {
    inventory_pb2.AVAILABLE:          ListingStatus.AVAILABLE,
    inventory_pb2.PENDING_PAYMENT:    ListingStatus.PENDING_PAYMENT,
    inventory_pb2.PENDING_COLLECTION: ListingStatus.PENDING_COLLECTION,
    inventory_pb2.SOLD:               ListingStatus.SOLD,
}


class InventoryServicer(inventory_pb2_grpc.InventoryServiceServicer):
    async def LockListing(self, request, context):
        new_status = _STATUS_MAP.get(request.new_status)
        if new_status is None:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid new_status value.")
            return inventory_pb2.LockListingResponse()

        async with SessionLocal() as db:
            try:
                new_version = await lock_listing(
                    db,
                    request.listing_id,
                    request.expected_version,
                    new_status,
                )
                return inventory_pb2.LockListingResponse(success=True, new_version=new_version)

            except ListingNotFoundError as e:
                await context.abort(grpc.StatusCode.NOT_FOUND, str(e))

            except LockConflictError as e:
                # ABORTED tells the caller "retry is possible — re-fetch first"
                await context.abort(grpc.StatusCode.ABORTED, str(e))

        return inventory_pb2.LockListingResponse()


async def start_grpc_server() -> grpc.aio.Server:
    server = grpc.aio.server()
    inventory_pb2_grpc.add_InventoryServiceServicer_to_server(InventoryServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    await server.start()
    print(f"gRPC server listening on port {GRPC_PORT}")
    return server
