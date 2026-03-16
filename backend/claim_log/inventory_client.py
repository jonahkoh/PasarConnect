"""
gRPC client for Inventory transitions triggered by Claim Log status updates.
"""
import os

import grpc
from dotenv import load_dotenv

import inventory_pb2
import inventory_pb2_grpc

load_dotenv()

INVENTORY_GRPC_HOST = os.getenv("INVENTORY_GRPC_HOST", "localhost")
INVENTORY_GRPC_PORT = os.getenv("INVENTORY_GRPC_PORT", "50051")
INVENTORY_GRPC_ADDR = f"{INVENTORY_GRPC_HOST}:{INVENTORY_GRPC_PORT}"


async def mark_listing_sold(listing_id: int, expected_version: int) -> int:
    """Transition PENDING_COLLECTION -> SOLD and return the new version."""
    async with grpc.aio.insecure_channel(INVENTORY_GRPC_ADDR) as channel:
        stub = inventory_pb2_grpc.InventoryServiceStub(channel)
        response = await stub.LockListing(
            inventory_pb2.LockListingRequest(
                listing_id=listing_id,
                expected_version=expected_version,
                new_status=inventory_pb2.SOLD,
            )
        )
    return response.new_version


async def rollback_listing_to_available(listing_id: int, expected_version: int) -> int:
    """Transition PENDING_COLLECTION -> AVAILABLE and return the new version."""
    async with grpc.aio.insecure_channel(INVENTORY_GRPC_ADDR) as channel:
        stub = inventory_pb2_grpc.InventoryServiceStub(channel)
        response = await stub.LockListing(
            inventory_pb2.LockListingRequest(
                listing_id=listing_id,
                expected_version=expected_version,
                new_status=inventory_pb2.AVAILABLE,
            )
        )
    return response.new_version
