"""
Async gRPC client for the Inventory Service.

Payment Service uses two status transitions:
  PENDING_PAYMENT → SOLD       mark_listing_sold()            (happy path)
  PENDING_PAYMENT → AVAILABLE  rollback_listing_to_available() (future use / manual ops)

Both calls use LockListing with an optimistic-lock version to prevent
concurrent updates from corrupting state (e.g., another service also
trying to update the same listing in the same instant).

Error handling strategy:
  - grpc.StatusCode.NOT_FOUND          → listing doesn't exist (caller maps to 404)
  - grpc.StatusCode.ABORTED            → version conflict, stale data (caller maps to 409)
  - grpc.StatusCode.UNAVAILABLE        → service down   → trigger compensating transaction
  - grpc.StatusCode.DEADLINE_EXCEEDED  → network timeout → trigger compensating transaction
  - Any other AioRpcError              → treated as a service failure → compensating transaction
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


async def _lock_listing(listing_id: int, expected_version: int, new_status: int) -> int:
    """
    Private helper — sends a single LockListing RPC to the Inventory Service.
    Returns the new version number on success.
    Raises grpc.aio.AioRpcError on any failure (callers let it propagate).
    """
    async with grpc.aio.insecure_channel(INVENTORY_GRPC_ADDR) as channel:
        stub = inventory_pb2_grpc.InventoryServiceStub(channel)
        response = await stub.LockListing(
            inventory_pb2.LockListingRequest(
                listing_id       = listing_id,
                expected_version = expected_version,
                new_status       = new_status,
            ),
            timeout=5.0,  # hard deadline — treat breach as DEADLINE_EXCEEDED
        )
    return response.new_version


async def lock_listing_pending_payment(listing_id: int, expected_version: int) -> int:
    """Transitions AVAILABLE → PENDING_PAYMENT.  Called when a payment intent is created."""
    return await _lock_listing(listing_id, expected_version, inventory_pb2.PENDING_PAYMENT)


async def mark_listing_sold(listing_id: int, expected_version: int) -> int:
    """Transitions PENDING_PAYMENT → SOLD.  Happy path after a charge succeeds."""
    return await _lock_listing(listing_id, expected_version, inventory_pb2.SOLD)


async def rollback_listing_to_available(listing_id: int, expected_version: int) -> int:
    """Transitions PENDING_PAYMENT → AVAILABLE.  Used when a payment is cancelled."""
    return await _lock_listing(listing_id, expected_version, inventory_pb2.AVAILABLE)
