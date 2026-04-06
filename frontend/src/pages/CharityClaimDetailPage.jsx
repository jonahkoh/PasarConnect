import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import TopNav from "../components/TopNav";
import ListingLocationMap from "../components/ListingLocationMap";
import { submitClaim, joinWaitlist } from "../lib/claimsApi";

export default function CharityClaimDetailPage({
  listings,
  selectedClaimIds,
  onToggleClaimQueue,
  onConfirmClaim,
  authUser,
  onToast,
}) {
  const navigate = useNavigate();
  const { listingId } = useParams();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [claimError, setClaimError] = useState(null);
  const [waitlistInfo, setWaitlistInfo] = useState(null); // { window_closes_at } on queue_window_active
  const [isJoiningWaitlist, setIsJoiningWaitlist] = useState(false);
  const [waitlistPosition, setWaitlistPosition] = useState(null); // position after joining

  const listing = useMemo(
    () => listings.find((item) => String(item.id) === listingId),
    [listingId, listings]
  );
  const isQueued = listing ? selectedClaimIds.includes(listing.id) : false;

  async function handleClaim() {
    if (!listing) return;
    setIsSubmitting(true);
    setClaimError(null);
    setWaitlistInfo(null);

    try {
      await submitClaim({
        listing_id: listing.id,
        charity_id: Number(authUser?.userId),
        listing_version: listing.version ?? 0,
        token: authUser?.token,
      });

      const updatedItem = onConfirmClaim(listing.id);
      const nextLabel = updatedItem?.quantityLabel ?? listing.quantityLabel;

      // Persist to sessionStorage so claimHistory survives a page refresh.
      try {
        const stored = JSON.parse(sessionStorage.getItem("claimHistory") || "[]");
        const entry = {
          historyId: `${listing.id}-${Date.now()}`,
          id: listing.id,
          name: listing.name,
          vendor: listing.vendor,
          status: "PENDING COLLECTION",
          claimedAtLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        };
        sessionStorage.setItem("claimHistory", JSON.stringify([entry, ...stored].slice(0, 50)));
      } catch {
        // sessionStorage write failure is non-fatal
      }

      onToast?.(`Claim confirmed for "${listing.name}". Remaining: ${nextLabel}.`);
      navigate("/charity", { replace: true });
    } catch (err) {
      const errorCode = err.detail?.error;
      if (errorCode === "queue_window_active" || errorCode === "queue_exists") {
        setWaitlistInfo(err.detail);
      } else {
        setClaimError(err.message);
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleJoinWaitlist() {
    if (!listing) return;
    setIsJoiningWaitlist(true);
    try {
      const result = await joinWaitlist({
        listing_id: listing.id,
        charity_id: Number(authUser?.userId),
        token: authUser?.token,
      });
      setWaitlistPosition(result.position);
      setWaitlistInfo(null);
    } catch (err) {
      setClaimError(err.message);
    } finally {
      setIsJoiningWaitlist(false);
    }
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
                  {listing.distanceKm != null && (
                    <div className="claim-page__info-row">
                      <span>Distance</span>
                      <strong>{listing.distanceKm} km away</strong>
                    </div>
                  )}
                  <div className="claim-page__info-row">
                    <span>Pickup address</span>
                    <strong>{listing.address}</strong>
                  </div>
                </section>

                <div className="claim-page__panel claim-page__panel--marketplace">
                  {claimError && (
                    <p className="claim-page__error" role="alert" style={{ color: "#c0392b", marginBottom: "0.75rem" }}>
                      {claimError}
                    </p>
                  )}

                  {waitlistPosition != null ? (
                    <p className="claim-page__queue-note" role="status">
                      You joined the waitlist.
                      {waitlistPosition > 0
                        ? ` Your position: #${waitlistPosition}.`
                        : " You're in the queue window — position assigned at window close."}
                    </p>
                  ) : waitlistInfo ? (
                    <div>
                      <p className="claim-page__queue-note" role="status">
                        {waitlistInfo.message ?? "This listing is in its charity queue window."}
                        {waitlistInfo.window_closes_at &&
                          ` Window closes: ${new Date(waitlistInfo.window_closes_at).toLocaleTimeString()}.`}
                      </p>
                      <button
                        type="button"
                        className="cart-summary__checkout"
                        onClick={handleJoinWaitlist}
                        disabled={isJoiningWaitlist}
                        style={{ marginTop: "0.5rem" }}
                      >
                        {isJoiningWaitlist ? "Joining..." : "Join Waitlist"}
                      </button>
                    </div>
                  ) : (
                    <>
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
                    </>
                  )}
                </div>
              </aside>
            </div>

            {listing.latitude != null && listing.longitude != null && (
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
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
