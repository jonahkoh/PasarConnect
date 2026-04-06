import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import TopNav from "../components/TopNav";
import FoodCard from "../components/FoodCard";
import CharityFilterSidebar from "../components/CharityFilterSidebar";
import CartSummary from "../components/CartSummary";
import LiveFoodMap from "../components/LiveFoodMap";

function parseQuantity(value) {
  const match = value.match(/\d+/);
  return match ? Number(match[0]) : 0;
}

export default function PublicMarketplacePage({
  listings,
  cart,
  totalCartItems,
  getCartQuantity,
  onAddToCart,
  onUpdateQuantity,
  isLoading = false,
}) {
  const navigate = useNavigate();
  const [addingId, setAddingId] = useState(null);
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("nearest");
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [selectedCategories, setSelectedCategories] = useState([]);
  const [selectedPickupWindows, setSelectedPickupWindows] = useState([]);
  const [selectedMapListingId, setSelectedMapListingId] = useState(listings[0]?.id ?? null);

  function toggleValue(setter, currentValues, value) {
    setter(
      currentValues.includes(value)
        ? currentValues.filter((item) => item !== value)
        : [...currentValues, value]
    );
  }

  function clearAllFilters() {
    setSelectedCategories([]);
    setSelectedPickupWindows([]);
  }

  const filteredListings = useMemo(() => {
    let result = [...listings];
    const keyword = search.trim().toLowerCase();

    if (keyword) {
      result = result.filter((item) =>
        [item.name, item.vendor, item.category].some((value) =>
          value.toLowerCase().includes(keyword)
        )
      );
    }

    if (selectedCategories.length > 0) {
      result = result.filter((item) => selectedCategories.includes(item.category));
    }

    if (selectedPickupWindows.length > 0) {
      result = result.filter((item) =>
        selectedPickupWindows.includes(item.pickupWindow)
      );
    }

    if (sortBy === "nearest") {
      result.sort((a, b) => a.distanceKm - b.distanceKm);
    } else if (sortBy === "name") {
      result.sort((a, b) => a.name.localeCompare(b.name));
    }

    return result;
  }, [listings, search, selectedCategories, selectedPickupWindows, sortBy]);

  const filteredMapListings = useMemo(
    () => filteredListings.filter((item) => typeof item.latitude === "number" && typeof item.longitude === "number"),
    [filteredListings]
  );

  useEffect(() => {
    if (filteredMapListings.some((item) => item.id === selectedMapListingId)) {
      return;
    }

    setSelectedMapListingId(filteredMapListings[0]?.id ?? null);
  }, [filteredMapListings, selectedMapListingId]);

  function handlePreviewLocation(item) {
    setSelectedMapListingId(item.id);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function handleOpenDetail(item) {
    navigate(`/marketplace/${item.id}`);
  }

  const cartItems = useMemo(
    () =>
      cart.map((entry) => ({
        ...entry,
        lineTotal: entry.quantity * entry.unitPrice,
      })),
    [cart]
  );

  const subtotal = useMemo(
    () => cart.reduce((sum, entry) => sum + entry.quantity * entry.unitPrice, 0),
    [cart]
  );

  async function handleAdd(item) {
    const currentQuantity = getCartQuantity(item.id);
    const maxQuantity = parseQuantity(item.quantityLabel);

    if (currentQuantity >= maxQuantity) {
      setMessage(`You already added all available "${item.name}" portions to cart.`);
      return;
    }

    setAddingId(item.id);
    setMessage("");

    await new Promise((resolve) => setTimeout(resolve, 250));

    onAddToCart(item);
    setAddingId(null);
    setMessage(`"${item.name}" was added to your cart.`);
  }

  return (
    <div className="app-shell">
      <TopNav cartCount={totalCartItems} />

      <main className="catalog-page">
        <div className="catalog-page__intro">
          <h1>Public Marketplace</h1>
          <p>
            Browse discounted food after the charity window closes and add items to
            your cart.
          </p>
        </div>

        <LiveFoodMap
          listings={filteredMapListings}
          selectedListingId={selectedMapListingId}
          onSelectListing={setSelectedMapListingId}
          isLoading={isLoading}
          eyebrow="Marketplace map"
          title="Discounted food pickup spots"
          subcopy="Browse the live marketplace visually, inspect rough pickup areas, and open a listing before adding it to your cart."
          selectedLabel="Selected marketplace item"
          routeBase="/marketplace"
          primaryActionLabel="Open item"
        />

        <section className="marketplace-dashboard">
          <CharityFilterSidebar
            selectedCategories={selectedCategories}
            selectedPickupWindows={selectedPickupWindows}
            onToggleCategory={(value) =>
              toggleValue(setSelectedCategories, selectedCategories, value)
            }
            onTogglePickupWindow={(value) =>
              toggleValue(setSelectedPickupWindows, selectedPickupWindows, value)
            }
            onClearAll={clearAllFilters}
            isMobileOpen={mobileFiltersOpen}
            onCloseMobile={() => setMobileFiltersOpen(false)}
          />

          <section className="catalog-content">
            <div className="catalog-toolbar catalog-toolbar--mobile">
              <button
                type="button"
                className="filters-btn"
                onClick={() => setMobileFiltersOpen(true)}
              >
                Filters
              </button>
            </div>

            <div className="catalog-toolbar">
              <div className="catalog-search">
                <span className="catalog-search__icon">⌕</span>
                <input
                  type="text"
                  placeholder="Search marketplace items..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>

              <select
                className="catalog-sort"
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
              >
                <option value="nearest">Nearest</option>
                <option value="name">A-Z</option>
              </select>
            </div>

            {message && <div className="alert-success">{message}</div>}

            {isLoading ? (
              <div className="empty-state" aria-live="polite">Loading marketplace listings…</div>
            ) : filteredListings.length === 0 ? (
              <div className="empty-state">No matching marketplace items found.</div>
            ) : (
              <section className="catalog-grid">
                {filteredListings.map((item) => {
                  const cartQuantity = getCartQuantity(item.id);
                  const availableQuantity = parseQuantity(item.quantityLabel);
                  const remainingQuantity = Math.max(
                    availableQuantity - cartQuantity,
                    0
                  );

                  return (
                    <FoodCard
                      key={item.id}
                      item={item}
                      onAction={handleAdd}
                      onPreview={handlePreviewLocation}
                      onOpenDetail={handleOpenDetail}
                      isProcessing={addingId === item.id}
                      isDisabled={remainingQuantity === 0}
                      actionLabel={
                        remainingQuantity === 0 ? "Max in Cart" : "Add to Cart"
                      }
                      helperText={`${item.pickupWindow} pickup`}
                    />
                  );
                })}
              </section>
            )}
          </section>

          <CartSummary
            items={cartItems}
            totalItems={totalCartItems}
            subtotal={subtotal}
            onUpdateQuantity={onUpdateQuantity}
            footer={
              <Link className="cart-summary__link" to="/marketplace/cart">
                Open full cart
              </Link>
            }
          />
        </section>
      </main>
    </div>
  );
}
