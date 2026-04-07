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

function parsePrice(value) {
  return Number(value.replace(/[^0-9.]/g, "")) || 0;
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
      fetchListingById(listing_id, authUser?.token)
        .then((listing) => {
          setCharityListings((prev) => [listing, ...prev]);
          setPublicListings((prev) => [listing, ...prev]);
        })
        .catch((err) => console.warn("[listing:new] fetch failed:", err.message));
    });

    socket.on("listing:window_closed", ({ listing_id }) => {
      const patch = { badge: "Window Closed", charityWindow: "" };
      setCharityListings((prev) =>
        prev.map((l) => (l.id === listing_id ? { ...l, ...patch } : l))
      );
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
    fetchListings(authUser.token, { signal: controller.signal })
      .then((data) => {
        setCharityListings(data);
        setPublicListings(data);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          console.error("[inventory] fetch failed:", err.message);
          // Keep mock data on failure so the UI stays usable.
        }
      })
      .finally(() => setIsListingsLoading(false));
    return () => controller.abort();
  }, [authUser]);

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
          // Marketplace items need amount > 0 for the payment service.
          // priceLabel is currently "Free" for all listings; use $2.00 SGD as the
          // demo marketplace price until the inventory API exposes a price field.
          unitPrice:       Math.max(parsePrice(item.priceLabel), 2.00),
          maxQuantity:     parseQuantity(item.quantityLabel),
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
