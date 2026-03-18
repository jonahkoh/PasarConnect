import { useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { mockListings } from "./data/mockListings";
import CharityClaimPage from "./pages/CharityClaimPage";
import MarketplaceCartPage from "./pages/MarketplaceCartPage";
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
  const [marketplaceCart, setMarketplaceCart] = useState([]);

  const totalCartItems = useMemo(
    () => marketplaceCart.reduce((sum, entry) => sum + entry.quantity, 0),
    [marketplaceCart]
  );

  function applyClaimSuccesses(successfulIds) {
    if (successfulIds.length === 0) {
      return;
    }

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
        <Route path="/" element={<Navigate to="/charity" replace />} />
        <Route
          path="/charity"
          element={
            <CharityClaimPage
              listings={charityListings}
              onApplyClaimSuccesses={applyClaimSuccesses}
            />
          }
        />
        <Route
          path="/marketplace"
          element={
            <PublicMarketplacePage
              cart={marketplaceCart}
              totalCartItems={totalCartItems}
              getCartQuantity={getCartQuantity}
              onAddToCart={addToMarketplaceCart}
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
      </Routes>
    </BrowserRouter>
  );
}
