from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import FoodListing, ListingStatus


class LockConflictError(Exception):
    """The listing was modified by another request before we got to it."""


class ListingNotFoundError(Exception):
    """No listing exists with the given ID."""


async def lock_listing(
    db: AsyncSession,
    listing_id: int,
    expected_version: int,
    new_status: ListingStatus,
) -> int:
    """
    Atomically transitions a listing's status.
    Returns the new version number on success.
    Raises LockConflictError or ListingNotFoundError on failure.
    """
    result = await db.execute(
        update(FoodListing)
        .where(
            FoodListing.id == listing_id,
            FoodListing.version == expected_version,
        )
        .values(
            status=new_status,
            version=FoodListing.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()

    if result.rowcount == 0:
        # Distinguish "not found" from "version mismatch" for better error messages
        check = await db.execute(
            select(FoodListing.id).where(FoodListing.id == listing_id)
        )
        if check.scalar_one_or_none() is None:
            raise ListingNotFoundError(f"Listing {listing_id} not found.")
        raise LockConflictError(
            f"Listing {listing_id} was already modified. Re-fetch and retry."
        )

    return expected_version + 1
