import os
import importlib

import grpc

INVENTORY_GRPC_HOST = os.getenv("INVENTORY_GRPC_HOST", "localhost")
INVENTORY_GRPC_PORT = os.getenv("INVENTORY_GRPC_PORT", "50051")
INVENTORY_GRPC_ADDR = f"{INVENTORY_GRPC_HOST}:{INVENTORY_GRPC_PORT}"


class InventoryServiceError(Exception):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


async def create_listing(payload: dict) -> int:
    inventory_pb2 = importlib.import_module("inventory_pb2")
    inventory_pb2_grpc = importlib.import_module("inventory_pb2_grpc")

    request = inventory_pb2.CreateListingRequest(
        vendor_id=payload["vendor_id"],
        title=payload["title"],
        description=payload.get("description") or "",
        quantity=payload.get("quantity") or 0,
        weight_kg=payload.get("weight_kg") or 0,
        expiry=payload.get("expiry") or "",
        image_url=payload.get("image_url") or "",
        latitude=payload.get("latitude") or 0.0,
        longitude=payload.get("longitude") or 0.0,
        price=payload.get("price") or 0.0,
    )

    try:
        async with grpc.aio.insecure_channel(INVENTORY_GRPC_ADDR) as channel:
            stub = inventory_pb2_grpc.InventoryServiceStub(channel)
            response = await stub.CreateListing(request)
    except grpc.aio.AioRpcError as exc:
        raise InventoryServiceError("Inventory service unavailable", status_code=503) from exc

    if not response.success:
        raise InventoryServiceError("Inventory failed to create listing", status_code=500)

    return response.listing_id


async def get_listing_created_at(listing_id: int) -> str:
    """
    Returns the listed_at (ISO-8601) timestamp for a listing.
    Raises InventoryServiceError on failure (caller can treat as non-fatal).
    """
    inventory_pb2 = importlib.import_module("inventory_pb2")
    inventory_pb2_grpc = importlib.import_module("inventory_pb2_grpc")

    try:
        async with grpc.aio.insecure_channel(INVENTORY_GRPC_ADDR) as channel:
            stub = inventory_pb2_grpc.InventoryServiceStub(channel)
            response = await stub.GetListing(
                inventory_pb2.GetListingRequest(listing_id=listing_id)
            )
    except grpc.aio.AioRpcError as exc:
        raise InventoryServiceError("Inventory service unavailable", status_code=503) from exc

    return response.listed_at
