import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import TopNav from "../components/TopNav";
import ListingLocationMap from "../components/ListingLocationMap";

function parsePrice(value) {
  return Number(value.replace(/[^0-9.]/g, "")) || 0;
}

function parseQuantity(value) {
  const match = value.match(/\d+/);
  return match ? Number(match[0]) : 0;
}

function formatCurrency(amount) {
  return new Intl.NumberFormat("en-SG", {
    style: "currency",
    currency: "SGD",
  }).format(amount);
}

export default function PublicMarketplaceDetailPage({
  listings,
  cart,
  getCartQuantity,
  onAddToCart,
  onUpdateQuantity,
}) {
  const navigate = useNavigate();
  const { listingId } = useParams();
  const [isAdding, setIsAdding] = useState(false);

  const listing = useMemo(
    () => listings.find((item) => String(item.id) === listingId),
    [listingId, listings]
  );

  const cartCount = useMemo(
    () => cart.reduce((sum, entry) => sum + entry.quantity, 0),
    [cart]
  );

  if (!listing) {
    return (
      <div className="app-shell">
        <TopNav cartCount={cartCount} />
        <main className="page">
          <div className="empty-state">
            Marketplace item not found. <Link to="/marketplace">Return to marketplace</Link>.
          </div>
        </main>
      </div>
    );
  }

  const cartQuantity = getCartQuantity(listing.id);
  const maxQuantity = parseQuantity(listing.quantityLabel);
  const remainingQuantity = Math.max(maxQuantity - cartQuantity, 0);

  async function handleAddToCart() {
    if (remainingQuantity <= 0) {
      return;
    }

    setIsAdding(true);
    await new Promise((resolve) => setTimeout(resolve, 250));
    onAddToCart(listing);
    setIsAdding(false);
  }

  function handleDecreaseQuantity() {
    onUpdateQuantity(listing.id, cartQuantity - 1);
  }

  function handleIncreaseQuantity() {
    if (cartQuantity >= maxQuantity) {
      return;
    }

    onUpdateQuantity(listing.id, cartQuantity + 1);
  }

  function handleRemoveFromCart() {
    onUpdateQuantity(listing.id, 0);
  }

  return (
    <div className="app-shell">
      <TopNav cartCount={cartCount} />

      <main className="page">
        <div className="claim-page claim-page--marketplace">
          <div className="claim-page__main claim-page__main--marketplace">
            <div className="claim-page__product">
              <section className="claim-page__gallery">
                <Link className="claim-page__back" to="/marketplace">
                  Back to marketplace
                </Link>

                <div className="claim-page__gallery-frame">
                  <img className="claim-page__image" src={listing.imageUrl} alt={listing.name} />
                </div>
              </section>

              <aside className="claim-page__product-info">
                <div className="claim-page__hero">
                  <div>
                    <p className="claim-page__eyebrow">Marketplace Item</p>
                    <h1>{listing.name}</h1>
                  </div>

                  <span className="claim-page__status">{listing.badge}</span>
                </div>

                <p className="claim-page__market-price">{listing.priceLabel}</p>

                <p className="claim-page__product-copy">
                  Inspect the rough pickup location, check what remains, and add this item to your cart when you are ready.
                </p>

                <section className="claim-page__info-strip">
                  <div className="claim-page__info-row">
                    <span>Pickup window</span>
                    <strong>{listing.pickupWindow}</strong>
                  </div>
                  <div className="claim-page__info-row">
                    <span>Vendor</span>
                    <strong>{listing.vendor}</strong>
                  </div>
                  <div className="claim-page__info-row">
                    <span>Distance</span>
                    <strong>{listing.distanceKm} km away</strong>
                  </div>
                  <div className="claim-page__info-row">
                    <span>Available now</span>
                    <strong>{remainingQuantity} of {maxQuantity}</strong>
                  </div>
                </section>

                <div className="claim-page__panel claim-page__panel--marketplace">
                  <div className="claim-page__market-actions">
                    <button
                      type="button"
                      className={`claim-page__queue-button${cartQuantity > 0 ? " claim-page__queue-button--danger" : ""}`}
                      onClick={cartQuantity > 0 ? handleRemoveFromCart : handleAddToCart}
                      disabled={cartQuantity === 0 && (remainingQuantity <= 0 || isAdding)}
                    >
                      {cartQuantity > 0
                        ? "Remove From Cart"
                        : remainingQuantity <= 0
                          ? "Max In Cart"
                          : isAdding
                            ? "Adding..."
                            : "Add To Cart"}
                    </button>

                    {cartQuantity > 0 && (
                      <div className="quantity-stepper claim-page__stepper">
                        <button
                          type="button"
                          onClick={handleDecreaseQuantity}
                          disabled={cartQuantity <= 0}
                        >
                          -
                        </button>
                        <span>{cartQuantity}</span>
                        <button
                          type="button"
                          onClick={handleIncreaseQuantity}
                          disabled={cartQuantity >= maxQuantity}
                        >
                          +
                        </button>
                      </div>
                    )}
                  </div>

                  {cartQuantity > 0 && (
                    <p className="claim-page__queue-note">
                      You already have {cartQuantity} in your cart. Max allowed: {maxQuantity}.
                    </p>
                  )}

                  <div className="claim-page__panel-footer">
                    <button
                      type="button"
                      className="cart-summary__checkout"
                      onClick={() => navigate("/marketplace/cart")}
                    >
                      Go To Cart
                    </button>

                    <button
                      type="button"
                      className="claim-page__secondary"
                      onClick={() => navigate("/marketplace")}
                    >
                      Continue Browsing
                    </button>
                  </div>
                </div>
              </aside>
            </div>

            <section className="claim-page__map-section">
              <div className="claim-page__map-copy">
                <p className="claim-page__eyebrow">Marketplace pickup map</p>
                <h2>Where to collect this item</h2>
                <p>
                  This map shows the rough pickup point so you can decide whether the route works before checkout.
                </p>
              </div>

              <ListingLocationMap
                listings={[listing]}
                selectedListingId={listing.id}
                interactive={false}
                className="claim-page__map"
                zoom={15}
              />
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}
