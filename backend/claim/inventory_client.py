"""
Thin async gRPC client for the Inventory Service.
Called during POST /claims to atomically transition a listing to PENDING_COLLECTION.
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


async def lock_listing_pending_collection(listing_id: int, expected_version: int) -> int:
    """
    Sends a LockListing RPC to Inventory.
    Returns the new version number on success.
    Raises grpc.RpcError on failure (caller maps the status code to an HTTP error).
    """
    async with grpc.aio.insecure_channel(INVENTORY_GRPC_ADDR) as channel:
        stub = inventory_pb2_grpc.InventoryServiceStub(channel)
        response = await stub.LockListing(
            inventory_pb2.LockListingRequest(
                listing_id       = listing_id,
                expected_version = expected_version,
                new_status       = inventory_pb2.PENDING_COLLECTION,
            )
        )
    return response.new_version


async def rollback_listing_to_available(listing_id: int, expected_version: int) -> int:
    """
    Compensating transaction helper.
    Reverts PENDING_COLLECTION -> AVAILABLE when downstream claim logging fails.
    Returns the new version after rollback.
    """
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


async def mark_listing_sold(listing_id: int, expected_version: int) -> int:
    """
    Finalize listing collection by transitioning PENDING_COLLECTION -> SOLD.
    Returns the new version after the transition.
    """
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