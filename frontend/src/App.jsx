import { useEffect, useMemo, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { mockListings } from "./data/mockListings";
import { mockPublicListings } from "./data/mockPublicListings";
import { fetchListings } from "./lib/inventoryApi";
import VendorDashboardPage from "./features/vendor/pages/VendorDashboardPage";
import CharityClaimPage from "./pages/CharityClaimPage";
import CharityClaimDetailPage from "./pages/CharityClaimDetailPage";
import LandingPage from "./pages/LandingPage";
import LoginPage from "./pages/LoginPage";
import MarketplaceCartPage from "./pages/MarketplaceCartPage";
import PublicMarketplaceDetailPage from "./pages/PublicMarketplaceDetailPage";
import PublicMarketplacePage from "./pages/PublicMarketplacePage";

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
  const [charityListings, setCharityListings] = useState(mockListings);
  const [publicListings, setPublicListings] = useState(mockPublicListings);

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
          id: item.id,
          name: item.name,
          vendor: item.vendor,
          imageUrl: item.imageUrl,
          quantity: 1,
          unitPrice: parsePrice(item.priceLabel),
          maxQuantity: parseQuantity(item.quantityLabel),
          pickupWindow: item.pickupWindow ?? "Self pickup",
          location: item.vendor,
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
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/charity"
          element={
            <CharityClaimPage
              listings={charityListings}
              selectedClaimIds={selectedClaimIds}
              onToggleClaimQueue={toggleClaimQueue}
              onRemoveFromClaimQueue={removeFromClaimQueue}
              onApplyClaimSuccesses={applyClaimSuccesses}
              isLoading={isListingsLoading}
            />
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
            />
          }
        />
        <Route
          path="/marketplace"
          element={
            <PublicMarketplacePage
              listings={publicListings}
              cart={marketplaceCart}
              totalCartItems={totalCartItems}
              getCartQuantity={getCartQuantity}
              onAddToCart={addToMarketplaceCart}
              onUpdateQuantity={updateMarketplaceCartItem}
              isLoading={isListingsLoading}
            />
          }
        />
        <Route
          path="/marketplace/:listingId"
          element={
            <PublicMarketplaceDetailPage
              listings={publicListings}
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
            />
          }
        />
        <Route path="/vendor" element={<VendorDashboardPage />} />
      </Routes>
    </BrowserRouter>
  );
}
