import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import TopNav from "../components/TopNav";
import ListingLocationMap from "../components/ListingLocationMap";

export default function CharityClaimDetailPage({
  listings,
  selectedClaimIds,
  onToggleClaimQueue,
  onConfirmClaim,
}) {
  const navigate = useNavigate();
  const { listingId } = useParams();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const listing = useMemo(
    () => listings.find((item) => String(item.id) === listingId),
    [listingId, listings]
  );
  const isQueued = listing ? selectedClaimIds.includes(listing.id) : false;

  async function handleClaim() {
    if (!listing) {
      return;
    }

    setIsSubmitting(true);
    await new Promise((resolve) => setTimeout(resolve, 400));

    const updatedItem = onConfirmClaim(listing.id);
    const nextLabel = updatedItem?.quantityLabel ?? listing.quantityLabel;

    navigate("/charity", {
      replace: true,
      state: {
        message: `Claim confirmed for "${listing.name}". Remaining quantity: ${nextLabel}.`,
      },
    });
  }

  if (!listing) {
    return (
      <div className="app-shell">
        <TopNav />
        <main className="page">
          <div className="empty-state">
            Listing not found. <Link to="/charity">Return to charity listings</Link>.
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <TopNav />

      <main className="page">
        <div className="claim-page claim-page--charity">
          <div className="claim-page__main claim-page__main--marketplace">
            <div className="claim-page__product">
              <section className="claim-page__gallery">
                <Link className="claim-page__back" to="/charity">
                  Back to listings
                </Link>

                <div className="claim-page__gallery-frame">
                  <img
                    className="claim-page__image"
                    src={listing.imageUrl}
                    alt={listing.name}
                  />
                </div>
              </section>

              <aside className="claim-page__product-info">
                <div className="claim-page__hero">
                  <div>
                    <p className="claim-page__eyebrow">Confirm Charity Claim</p>
                    <h1>{listing.name}</h1>
                  </div>

                  <span className="claim-page__status">{listing.badge}</span>
                </div>

                <p className="claim-page__market-price">{listing.quantityLabel}</p>

                <p className="claim-page__product-copy">
                  No payment is required. Confirm the claim under your organization and proceed with pickup coordination.
                </p>

                <section className="claim-page__info-strip">
                  <div className="claim-page__info-row">
                    <span>Pickup window</span>
                    <strong>{listing.pickupWindow}</strong>
                  </div>
                  <div className="claim-page__info-row">
                    <span>Pickup from</span>
                    <strong>{listing.vendor}</strong>
                  </div>
                  <div className="claim-page__info-row">
                    <span>Distance</span>
                    <strong>{listing.distanceKm} km away</strong>
                  </div>
                  <div className="claim-page__info-row">
                    <span>Pickup address</span>
                    <strong>{listing.address}</strong>
                  </div>
                </section>

                <div className="claim-page__panel claim-page__panel--marketplace">
                  <div className="claim-page__market-actions">
                    <button
                      type="button"
                      className={`claim-page__queue-button${isQueued ? " claim-page__queue-button--danger" : ""}`}
                      onClick={() => onToggleClaimQueue(listing.id)}
                      disabled={listing.status !== "AVAILABLE"}
                    >
                      {isQueued ? "Remove From Queue" : "Add To Claim Queue"}
                    </button>
                  </div>

                  {isQueued && (
                    <p className="claim-page__queue-note">
                      This listing is already in your claim queue on the main page.
                    </p>
                  )}

                  <div className="claim-page__panel-footer">
                    <button
                      type="button"
                      className="cart-summary__checkout"
                      onClick={handleClaim}
                      disabled={isSubmitting || listing.status !== "AVAILABLE"}
                    >
                      {isSubmitting ? "Submitting..." : "Claim Now"}
                    </button>

                    <button
                      type="button"
                      className="claim-page__secondary"
                      onClick={() => navigate("/charity")}
                    >
                      Continue Browsing
                    </button>
                  </div>
                </div>
              </aside>
            </div>

            <section className="claim-page__map-section">
              <div className="claim-page__map-copy">
                <p className="claim-page__eyebrow">Rough static pickup map</p>
                <h2>Where to pick this up</h2>
                <p>
                  This is a rough visual location for planning and coordination before pickup.
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
