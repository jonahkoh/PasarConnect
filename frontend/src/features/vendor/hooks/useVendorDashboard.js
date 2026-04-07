import { useEffect, useState } from "react";
import { fetchVendorListings } from "../api/vendorApi";
import { fetchActiveClaimForListing } from "../../../lib/claimsApi";

export function useVendorDashboard(authUser, socket) {
  const [listings, setListings] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshCount, setRefreshCount] = useState(0);

  function refetch() {
    setRefreshCount((c) => c + 1);
  }

  useEffect(() => {
    if (!authUser?.token) {
      setIsLoading(false);
      return;
    }

    let isMounted = true;

    async function loadDashboard() {
      setIsLoading(true);
      setError("");
      try {
        const data = await fetchVendorListings(authUser.token, authUser.userId);
        if (!isMounted) return;

        // For listings awaiting vendor approval, resolve the claim_id from the DB
        // so Approve/Reject buttons appear even if the socket event was missed.
        // PENDING_COLLECTION means charity has claimed but not yet arrived — no buttons yet.
        const pendingStatuses = new Set(["AWAITING_VENDOR_APPROVAL"]);
        const withClaims = await Promise.all(
          data.map(async (listing) => {
            if (!pendingStatuses.has(listing.status)) return listing;
            try {
              const claim = await fetchActiveClaimForListing(listing.id, authUser.token);
              return claim ? { ...listing, pendingClaimId: claim.id } : listing;
            } catch {
              return listing;
            }
          })
        );

        if (!isMounted) return;
        setListings(withClaims);
      } catch (loadError) {
        if (!isMounted) return;
        setError(loadError?.message ?? "Unable to load vendor listings. Please try again.");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    loadDashboard();
    return () => { isMounted = false; };
  }, [authUser?.token, authUser?.userId, refreshCount]);

  // Subscribe to per-listing socket rooms once listings are loaded
  useEffect(() => {
    if (!socket || listings.length === 0) return;
    listings.forEach((listing) => {
      socket.emit("subscribe:listing", { listing_id: listing.id });
    });
  }, [socket, listings]);

  // Refresh vendor listings when a new listing is created (via socket event)
  useEffect(() => {
    if (!socket || !authUser?.token) return;

    function handleListingNew() {
      // Re-fetch so the new listing (if it belongs to this vendor) appears immediately
      fetchVendorListings(authUser.token, authUser.userId)
        .then((data) => setListings(data))
        .catch(() => {});
    }

    socket.on("listing:new", handleListingNew);
    return () => socket.off("listing:new", handleListingNew);
  }, [socket, authUser?.token, authUser?.userId]);

  return {
    listings,
    setListings,
    notifications,
    setNotifications,
    isLoading,
    error,
    refetch,
  };
}
