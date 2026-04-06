import { useEffect, useState } from "react";
import { fetchVendorListings } from "../api/vendorApi";

export function useVendorDashboard(authUser, socket) {
  const [listings, setListings] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!authUser?.token) {
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    const controller = new AbortController();

    async function loadDashboard() {
      setIsLoading(true);
      setError("");
      try {
        const data = await fetchVendorListings(authUser.token, authUser.userId);
        if (!isMounted) return;
        setListings(data);
      } catch (loadError) {
        if (!isMounted) return;
        setError(loadError?.message ?? "Unable to load vendor listings. Please try again.");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    loadDashboard();
    return () => {
      isMounted = false;
      controller.abort();
    };
  }, [authUser?.token, authUser?.userId]);

  // Subscribe to per-listing socket rooms once listings are loaded
  useEffect(() => {
    if (!socket || listings.length === 0) return;
    listings.forEach((listing) => {
      socket.emit("subscribe:listing", { listing_id: listing.id });
    });
  }, [socket, listings]);

  return {
    listings,
    setListings,
    notifications,
    setNotifications,
    isLoading,
    error,
  };
}
