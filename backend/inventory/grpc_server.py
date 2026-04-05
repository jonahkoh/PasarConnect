import grpc
import grpc.aio
from datetime import datetime, timezone

import geohash2
import inventory_pb2
import inventory_pb2_grpc
from database import SessionLocal
from lock_service import LockConflictError, ListingNotFoundError, lock_listing
from models import FoodListing, ListingStatus

GRPC_PORT = 50051
GEOHASH_STORE_PRECISION = 6  # ~1.2 km cell — matches HTTP layer constant

# Map the proto enum integers to our SQLAlchemy enum values
_STATUS_MAP = {
    inventory_pb2.AVAILABLE:          ListingStatus.AVAILABLE,
    inventory_pb2.PENDING_PAYMENT:    ListingStatus.PENDING_PAYMENT,
    inventory_pb2.PENDING_COLLECTION: ListingStatus.PENDING_COLLECTION,
    inventory_pb2.SOLD_PENDING_COLLECTION: ListingStatus.SOLD_PENDING_COLLECTION,
    inventory_pb2.SOLD:               ListingStatus.SOLD,
}


class InventoryServicer(inventory_pb2_grpc.InventoryServiceServicer):
    async def CreateListing(self, request, context):
        if not request.vendor_id or not request.title:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "vendor_id and title are required")
            return inventory_pb2.CreateListingResponse()

        if request.quantity <= 0 and request.weight_kg <= 0:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Either quantity or weight_kg must be provided",
            )
            return inventory_pb2.CreateListingResponse()

        expiry_raw = request.expiry
        if not expiry_raw:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "expiry is required",
            )
            return inventory_pb2.CreateListingResponse()

        try:
            normalized = expiry_raw.replace("Z", "+00:00")
            expiry = datetime.fromisoformat(normalized)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid expiry format")
            return inventory_pb2.CreateListingResponse()

        async with SessionLocal() as db:
            # Treat 0.0 as "not provided" — same sentinel pattern as quantity/weight_kg.
            # Proto3 doubles default to 0.0 when the field is omitted by the caller.
            latitude  = request.latitude  if request.latitude  != 0.0 else None
            longitude = request.longitude if request.longitude != 0.0 else None
            geohash_val = None
            if latitude is not None and longitude is not None:
                geohash_val = geohash2.encode(latitude, longitude, precision=GEOHASH_STORE_PRECISION)

            record = FoodListing(
                vendor_id=request.vendor_id,
                title=request.title,
                description=request.description or None,
                quantity=request.quantity if request.quantity > 0 else None,
                weight_kg=request.weight_kg if request.weight_kg > 0 else None,
                expiry=expiry,
                image_url=request.image_url or None,
                latitude=latitude,
                longitude=longitude,
                geohash=geohash_val,
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)

            return inventory_pb2.CreateListingResponse(success=True, listing_id=record.id)

    async def GetListing(self, request, context):
        if request.listing_id <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "listing_id must be > 0")
            return inventory_pb2.GetListingResponse()

        async with SessionLocal() as db:
            record = await db.get(FoodListing, request.listing_id)
            if record is None:
                await context.abort(
                    grpc.StatusCode.NOT_FOUND,
                    f"Listing {request.listing_id} not found",
                )
                return inventory_pb2.GetListingResponse()

            return inventory_pb2.GetListingResponse(
                listing_id=record.id,
                version=record.version,
                status=record.status.value,
                listed_at=record.created_at.isoformat() if record.created_at else "",
            )

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
