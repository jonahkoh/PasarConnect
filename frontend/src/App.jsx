import { useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { fetchListingById, fetchListings } from "./lib/inventoryApi";
import { useSocket } from "./hooks/useSocket";
import Toast from "./components/Toast";
import VendorDashboardPage from "./features/vendor/pages/VendorDashboardPage";
import CharityClaimPage from "./pages/CharityClaimPage";
import ClaimHistoryPage from "./pages/ClaimHistoryPage";
import CharityClaimDetailPage from "./pages/CharityClaimDetailPage";
import LandingPage from "./pages/LandingPage";
import LoginPage from "./pages/LoginPage";
import MarketplaceCartPage from "./pages/MarketplaceCartPage";
import PublicMarketplaceDetailPage from "./pages/PublicMarketplaceDetailPage";
import PublicMarketplacePage from "./pages/PublicMarketplacePage";
import PurchaseHistoryPage from "./pages/PurchaseHistoryPage";
import RegisterPage from "./pages/RegisterPage";

// Simple auth guard: if the user isn't logged in (or has the wrong role) redirect
// them to the login page pre-selecting the correct role tab.
function ProtectedRoute({ authUser, requiredRole, loginRole, children }) {
  if (!authUser?.token) {
    return <Navigate to={`/login?role=${loginRole ?? requiredRole}`} replace />;
  }
  if (requiredRole && authUser.role !== requiredRole) {
    return <Navigate to={`/login?role=${loginRole ?? requiredRole}`} replace />;
  }
  return children;
}

function parseQuantity(value) {
  const match = value.match(/\d+/);
  return match ? Number(match[0]) : 0;
}

function decrementQuantityLabel(label) {
  const current = parseQuantity(label);
  const next = Math.max(current - 1, 0);
  return label.replace(/\d+/, String(next));
}

export default function App() {
  const [charityListings, setCharityListings] = useState([]);
  const [publicListings, setPublicListings] = useState([]);

  // Read auth token written by LoginPage into sessionStorage.
  // const is intentional: authUser never changes during a session.
  const [authUser] = useState(() => {
    const token  = sessionStorage.getItem("authToken");
    const role   = sessionStorage.getItem("authRole");
    const userId = sessionStorage.getItem("authUserId");
    return token ? { token, role, userId } : null;
  });

  // Start in loading state only when a token is present so the pages don't
  // flash mock data before real listings arrive.
  const [isListingsLoading, setIsListingsLoading] = useState(Boolean(authUser?.token));

  const socket = useSocket(authUser);
  const [toast, setToast] = useState(null);

  // ── User location (for geohash-based nearby search + distance display) ───────────
  const [userLocation, setUserLocation] = useState(() => {
    try {
      const stored = sessionStorage.getItem("userLocation");
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });

  // Request geolocation for any authenticated user as soon as they log in.
  // Result stored in sessionStorage so the prompt only fires once per session.
  useEffect(() => {
    if (!authUser?.token || userLocation) return;
    navigator.geolocation?.getCurrentPosition(
      (pos) => {
        const loc = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setUserLocation(loc);
        try { sessionStorage.setItem("userLocation", JSON.stringify(loc)); } catch {}
      },
      () => { /* permission denied — fall back to showing all listings */ },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 300_000 }
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authUser?.token]);

  // Socket event handlers
  // Auto-dismiss toast after 5 s
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(t);
  }, [toast]);

  // Socket event handlers — all state mutations live here since App owns the listings state
  useEffect(() => {
    if (!socket) return;

    socket.on("listing:new", ({ listing_id }) => {
      if (!listing_id) return;
      fetchListingById(listing_id, authUser?.token, userLocation)
        .then((listing) => {
          setCharityListings((prev) => [listing, ...prev]);
        })
        .catch((err) => console.warn("[listing:new] fetch failed:", err.message));
    });

    socket.on("listing:window_closed", ({ listing_id }) => {
      const patch = { badge: "Window Closed", charityWindow: "" };
      setCharityListings((prev) =>
        prev.map((l) => (l.id === listing_id ? { ...l, ...patch } : l))
      );
      fetchListingById(listing_id, authUser?.token, userLocation)
        .then((listing) => {
          if (listing.price != null) setPublicListings((prev) => [listing, ...prev]);
        })
        .catch((err) => console.warn("[listing:window_closed] fetch failed:", err.message));
    });

    socket.on("claim:success", ({ listing_id }) => {
      const patch = { status: "UNAVAILABLE", badge: "Claimed", charityWindow: "" };
      setCharityListings((prev) =>
        prev.map((l) => (l.id === listing_id ? { ...l, ...patch } : l))
      );
    });

    socket.on("claim:promoted", () => {
      setToast("You've been promoted in the waitlist! Open the listing to accept your slot.");
    });

    // Global handler so offers are captured even when CharityClaimPage is not mounted
    // (e.g. charity is browsing a /charity/:id detail page).
    socket.on("claim:offered", (payload) => {
      try {
        const pending = JSON.parse(sessionStorage.getItem("pendingOffers") || "[]");
        if (!pending.some((o) => o.listing_id === payload.listing_id)) {
          sessionStorage.setItem("pendingOffers", JSON.stringify([...pending, payload]));
        }
      } catch { /* non-fatal */ }
      setToast("You've been offered a listing slot! Go to the Claim page to accept.");
    });

    // Notify waiting charities of their queue position after window resolution.
    socket.on("claim:queued", (payload) => {
      try {
        const wl = JSON.parse(sessionStorage.getItem("joinedWaitlist") || "{}");
        if (wl[payload.listing_id]) {
          wl[payload.listing_id] = { status: "WAITING", position: payload.position };
          sessionStorage.setItem("joinedWaitlist", JSON.stringify(wl));
        }
      } catch { /* non-fatal */ }
      setToast(`Queue position #${payload.position} assigned. You'll be notified when it's your turn.`);
    });

    socket.on("payment:confirmed", ({ listing_id }) => {
      // Buyer confirmed payment — mark listing as unavailable in the public feed.
      const patch = { status: "SOLD_PENDING_COLLECTION", badge: "Sold", charityWindow: "" };
      setPublicListings((prev) =>
        prev.map((l) => (l.id === listing_id ? { ...l, ...patch } : l))
      );
    });

    return () => {
      socket.off("listing:new");
      socket.off("listing:window_closed");
      socket.off("claim:success");
      socket.off("claim:promoted");
      socket.off("claim:offered");
      socket.off("claim:queued");
      socket.off("payment:confirmed");
    };
  }, [socket]);

  useEffect(() => {
    if (!authUser?.token) return;
    const controller = new AbortController();
    setIsListingsLoading(true);
    fetchListings(authUser.token, { signal: controller.signal, userCoords: userLocation })
      .then((data) => {
        const windowMs = parseFloat(import.meta.env.VITE_QUEUE_WINDOW_MINUTES || "5") * 60 * 1000;
        const now = Date.now();
        setCharityListings(data);
        setPublicListings(data.filter((l) => (!l.listedAt || (now - new Date(l.listedAt).getTime()) >= windowMs) && l.price != null));
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          console.error("[inventory] fetch failed:", err.message);
        }
      })
      .finally(() => setIsListingsLoading(false));
    return () => controller.abort();
  }, [authUser]);

  // When location becomes available mid-session, re-fetch to populate distanceKm.
  useEffect(() => {
    if (!authUser?.token || !userLocation) return;
    const controller = new AbortController();
    fetchListings(authUser.token, { signal: controller.signal, userCoords: userLocation })
      .then((data) => {
        const windowMs = parseFloat(import.meta.env.VITE_QUEUE_WINDOW_MINUTES || "5") * 60 * 1000;
        const now = Date.now();
        setCharityListings(data);
        setPublicListings(data.filter((l) => (!l.listedAt || (now - new Date(l.listedAt).getTime()) >= windowMs) && l.price != null));
      })
      .catch((err) => {
        if (err.name !== "AbortError") console.warn("[inventory] geo refetch:", err.message);
      });
    return () => controller.abort();
  }, [userLocation]); // eslint-disable-line react-hooks/exhaustive-deps

  const [selectedClaimIds, setSelectedClaimIds] = useState([]);
  const [marketplaceCart, setMarketplaceCart] = useState([]);

  const totalCartItems = useMemo(
    () => marketplaceCart.reduce((sum, entry) => sum + entry.quantity, 0),
    [marketplaceCart]
  );

  function applyClaimSuccesses(successfulIds) {
    if (successfulIds.length === 0) {
      return;
    }

    setSelectedClaimIds((prev) =>
      prev.filter((id) => !successfulIds.includes(id))
    );

    setCharityListings((prev) =>
      prev.map((entry) => {
        if (!successfulIds.includes(entry.id)) {
          return entry;
        }

        const nextQuantity = Math.max(parseQuantity(entry.quantityLabel) - 1, 0);

        return {
          ...entry,
          quantityLabel: decrementQuantityLabel(entry.quantityLabel),
          status: nextQuantity === 0 ? "UNAVAILABLE" : "AVAILABLE",
          badge: nextQuantity === 0 ? "Claimed" : "Available",
          charityWindow: nextQuantity === 0 ? "" : entry.charityWindow,
        };
      })
    );
  }

  function confirmCharityClaim(itemId) {
    let updatedListing = null;

    setSelectedClaimIds((prev) => prev.filter((id) => id !== itemId));

    setCharityListings((prev) =>
      prev.map((entry) => {
        if (entry.id !== itemId) {
          return entry;
        }

        const nextQuantity = Math.max(parseQuantity(entry.quantityLabel) - 1, 0);
        updatedListing = {
          ...entry,
          quantityLabel: decrementQuantityLabel(entry.quantityLabel),
          status: nextQuantity === 0 ? "UNAVAILABLE" : "AVAILABLE",
          badge: nextQuantity === 0 ? "Claimed" : "Available",
          charityWindow: nextQuantity === 0 ? "" : entry.charityWindow,
        };
        return updatedListing;
      })
    );

    return updatedListing;
  }

  function toggleClaimQueue(itemId) {
    setSelectedClaimIds((prev) =>
      prev.includes(itemId)
        ? prev.filter((id) => id !== itemId)
        : [...prev, itemId]
    );
  }

  function removeFromClaimQueue(itemId) {
    setSelectedClaimIds((prev) => prev.filter((id) => id !== itemId));
  }

  function getCartQuantity(itemId) {
    return marketplaceCart.find((entry) => entry.id === itemId)?.quantity ?? 0;
  }

  function addToMarketplaceCart(item) {
    setMarketplaceCart((prev) => {
      const existingItem = prev.find((entry) => entry.id === item.id);

      if (existingItem) {
        return prev.map((entry) =>
          entry.id === item.id
            ? {
                ...entry,
                quantity: Math.min(entry.quantity + 1, entry.maxQuantity),
              }
            : entry
        );
      }

      return [
        ...prev,
        {
          id:              item.id,
          name:            item.name,
          vendor:          item.vendor,
          imageUrl:        item.imageUrl,
          quantity:        1,
          unitPrice:       item.price ?? 0,
          maxQuantity:     1,
          pickupWindow:    item.pickupWindow ?? "Self pickup",
          location:        item.vendor,
          // Keep the inventory version so the payment service can verify no
          // concurrent modification has occurred (optimistic locking).
          listing_version: item.version ?? 0,
        },
      ];
    });
  }

  function updateMarketplaceCartItem(itemId, nextQuantity) {
    setMarketplaceCart((prev) => {
      if (nextQuantity <= 0) {
        return prev.filter((entry) => entry.id !== itemId);
      }

      return prev.map((entry) =>
        entry.id === itemId
          ? { ...entry, quantity: Math.min(nextQuantity, entry.maxQuantity) }
          : entry
      );
    });
  }

  function clearMarketplaceCart() {
    setMarketplaceCart([]);
  }

  return (
    <BrowserRouter>
      <Toast message={toast} onDismiss={() => setToast(null)} />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/charity"
          element={
            <ProtectedRoute authUser={authUser} requiredRole="charity">
            <CharityClaimPage
              listings={charityListings.filter((l) => l.status === "AVAILABLE")}
              selectedClaimIds={selectedClaimIds}
              onToggleClaimQueue={toggleClaimQueue}
              onRemoveFromClaimQueue={removeFromClaimQueue}
              onApplyClaimSuccesses={applyClaimSuccesses}
              isLoading={isListingsLoading}
              socket={socket}
              authUser={authUser}
              userLocation={userLocation}
            />
            </ProtectedRoute>
          }
        />
        <Route
          path="/charity/:listingId"
          element={
            <CharityClaimDetailPage
              listings={charityListings}
              selectedClaimIds={selectedClaimIds}
              onToggleClaimQueue={toggleClaimQueue}
              onConfirmClaim={confirmCharityClaim}
              authUser={authUser}
              onToast={setToast}
            />
          }
        />
        <Route
          path="/marketplace"
          element={
            <ProtectedRoute authUser={authUser} requiredRole="public" loginRole="marketplace">
              <PublicMarketplacePage
                listings={publicListings.filter((l) => l.status === "AVAILABLE")}
                cart={marketplaceCart}
                totalCartItems={totalCartItems}
                getCartQuantity={getCartQuantity}
                onAddToCart={addToMarketplaceCart}
                onUpdateQuantity={updateMarketplaceCartItem}
                isLoading={isListingsLoading}
                authUser={authUser}
                userLocation={userLocation}
              />
            </ProtectedRoute>
          }
        />
        <Route
          path="/marketplace/:listingId"
          element={
            <PublicMarketplaceDetailPage
              listings={publicListings.filter((l) => l.status === "AVAILABLE")}
              cart={marketplaceCart}
              getCartQuantity={getCartQuantity}
              onAddToCart={addToMarketplaceCart}
              onUpdateQuantity={updateMarketplaceCartItem}
            />
          }
        />
        <Route
          path="/marketplace/cart"
          element={
            <MarketplaceCartPage
              cart={marketplaceCart}
              totalCartItems={totalCartItems}
              onUpdateQuantity={updateMarketplaceCartItem}
              onClearCart={clearMarketplaceCart}
              authUser={authUser}
            />
          }
        />
        <Route
          path="/marketplace/orders"
          element={<PurchaseHistoryPage authUser={authUser} socket={socket} />}
        />
        <Route
          path="/charity/history"
          element={
            <ProtectedRoute authUser={authUser} requiredRole="charity">
              <ClaimHistoryPage authUser={authUser} socket={socket} />
            </ProtectedRoute>
          }
        />
        <Route path="/vendor" element={
          <ProtectedRoute authUser={authUser} requiredRole="vendor">
            <VendorDashboardPage authUser={authUser} socket={socket} />
          </ProtectedRoute>
        } />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/live-chats"
          element={
            <div style={{ padding: "80px 32px", textAlign: "center", fontFamily: "Inter, sans-serif" }}>
              <h2>Live Chats</h2>
              <p style={{ color: "#557468" }}>Coming soon — real-time chat with vendors and charities.</p>
            </div>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
