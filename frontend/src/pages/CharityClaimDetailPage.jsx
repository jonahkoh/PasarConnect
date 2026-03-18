import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import TopNav from "../components/TopNav";

export default function CharityClaimDetailPage({ listings, onConfirmClaim }) {
  const navigate = useNavigate();
  const { listingId } = useParams();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const listing = useMemo(
    () => listings.find((item) => String(item.id) === listingId),
    [listingId, listings]
  );

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
        <div className="claim-page">
          <div className="claim-page__main">
            <Link className="claim-page__back" to="/charity">
              Back to listings
            </Link>

            <div className="claim-page__hero">
              <div>
                <p className="claim-page__eyebrow">Confirm Charity Claim</p>
                <h1>{listing.name}</h1>
                <p>
                  No payment is required. Confirm the claim under your organization
                  and proceed with pickup coordination.
                </p>
              </div>

              <span className="claim-page__status">{listing.badge}</span>
            </div>

            <img
              className="claim-page__image"
              src={listing.imageUrl}
              alt={listing.name}
            />

            <section className="claim-page__details">
              <article>
                <h2>Quantity</h2>
                <p>{listing.quantityLabel}</p>
              </article>
              <article>
                <h2>Pickup Window</h2>
                <p>{listing.pickupWindow}</p>
              </article>
              <article>
                <h2>Location</h2>
                <p>{listing.vendor}</p>
              </article>
              <article>
                <h2>Distance</h2>
                <p>{listing.distanceKm} km away</p>
              </article>
            </section>
          </div>

          <aside className="claim-page__sidebar">
            <div className="claim-page__panel">
              <h2>Confirm Claim</h2>
              <p className="claim-page__panel-copy">
                This claim is processed under your charity organization. The system
                will reduce the available quantity after confirmation.
              </p>

              <button
                type="button"
                className="cart-summary__checkout"
                onClick={handleClaim}
                disabled={isSubmitting || listing.status !== "AVAILABLE"}
              >
                {isSubmitting ? "Submitting..." : "Confirm Claim"}
              </button>

              <button
                type="button"
                className="claim-page__secondary"
                onClick={() => navigate("/charity")}
              >
                Cancel
              </button>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
