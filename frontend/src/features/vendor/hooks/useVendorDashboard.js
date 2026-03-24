import { useEffect, useState } from "react";
import { fetchVendorDashboard } from "../api/vendorApi";

export function useVendorDashboard() {
  const [listings, setListings] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let isMounted = true;

    async function loadDashboard() {
      setIsLoading(true);
      setError("");

      try {
        const data = await fetchVendorDashboard();

        if (!isMounted) {
          return;
        }

        setListings(data.listings);
        setNotifications(data.notifications);
      } catch (loadError) {
        if (!isMounted) {
          return;
        }

        setError(
          loadError?.message ||
            "Unable to load vendor listings right now. Please try again."
        );
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    loadDashboard();

    return () => {
      isMounted = false;
    };
  }, []);

  return {
    listings,
    notifications,
    isLoading,
    error,
  };
}
