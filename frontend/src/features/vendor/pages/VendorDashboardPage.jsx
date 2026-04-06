import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import TopNav from "../../../components/TopNav";
import Toast from "../../../components/Toast";
import VendorDashboardSummary from "../components/VendorDashboardSummary";
import VendorListingCard from "../components/VendorListingCard";
import VendorNotificationsPanel from "../components/VendorNotificationsPanel";
import VendorCreateListingModal from "../components/VendorCreateListingModal";
import { useVendorDashboard } from "../hooks/useVendorDashboard";
import { approveClaim, rejectClaim } from "../api/vendorApi";

export default function VendorDashboardPage({ authUser, socket }) {
  const navigate = useNavigate();

  // Guard: if session is missing or wrong role, redirect to login immediately.
  useEffect(() => {
    if (!authUser?.token || authUser.role !== "vendor") {
      navigate("/login?role=vendor", { replace: true });
    }
  }, [authUser, navigate]);

  const { listings, setListings, notifications, setNotifications, isLoading, error, refetch } =
    useVendorDashboard(authUser, socket);

  const [showModal, setShowModal] = useState(false);
  const [toast, setToast] = useState(null);
  const [actionError, setActionError] = useState(null); // { claimId, message }

  function showToast(msg) {
    setToast(msg);
    setTimeout(() => setToast(null), 5000);
  }

  function handleListingCreated(result) {
    setShowModal(false);
    showToast(`Listing #${result.listing_id} created. The charity queue window is now open.`);
    // Re-fetch vendor listings so the new one appears immediately.
    refetch();
  }

  async function handleApproveClaim(claimId) {
    setActionError(null);
    try {
      await approveClaim(claimId, authUser?.token);
      showToast(`Claim #${claimId} approved.`);
      setListings((prev) =>
        prev.map((l) =>
          l.pendingClaimId === claimId ? { ...l, status: "SOLD", pendingClaimId: null } : l
        )
      );
    } catch (err) {
      setActionError({ claimId, message: err.message });
    }
  }

  async function handleRejectClaim(claimId) {
    setActionError(null);
    try {
      await rejectClaim(claimId, authUser?.token);
      showToast(`Claim #${claimId} rejected. Listing returned to available.`);
      setListings((prev) =>
        prev.map((l) =>
          l.pendingClaimId === claimId
            ? { ...l, status: "AVAILABLE", pendingClaimId: null }
            : l
        )
      );
    } catch (err) {
      setActionError({ claimId, message: err.message });
    }
  }

  return (
    <div className="app-shell">
      <TopNav />
      <Toast message={toast} onDismiss={() => setToast(null)} />

      {showModal && (
        <VendorCreateListingModal
          token={authUser?.token}
          onCreated={handleListingCreated}
          onClose={() => setShowModal(false)}
        />
      )}

      <main className="page vendor-page">
        <section className="vendor-hero">
          <div>
            <p className="vendor-eyebrow">Vendor Console</p>
            <h1>Track surplus food listings from one place.</h1>
            <p className="vendor-hero__copy">
              Create listings, monitor their charity and public lifecycle, and
              approve or reject charity claims in real time.
            </p>
          </div>
          <button
            type="button"
            className="landing-button landing-button--primary"
            onClick={() => setShowModal(true)}
            style={{ alignSelf: "flex-start" }}
          >
            + Create Listing
          </button>
        </section>

        {isLoading ? (
          <div className="empty-state">Loading vendor dashboard...</div>
        ) : error ? (
          <div className="vendor-error-banner" role="alert">{error}</div>
        ) : (
          <>
            <VendorDashboardSummary listings={listings} />

            <section className="vendor-dashboard-layout">
              <section className="vendor-listings-section">
                <div className="vendor-panel__header">
                  <div>
                    <h2>Current Listings</h2>
                    <p>Filtered to your vendor account from the Inventory Service.</p>
                  </div>
                </div>

                {listings.length === 0 ? (
                  <div className="empty-state">
                    No active listings yet.{" "}
                    <button
                      type="button"
                      className="landing-button landing-button--primary"
                      onClick={() => setShowModal(true)}
                      style={{ display: "inline", padding: "0.3rem 0.75rem", fontSize: "0.9rem" }}
                    >
                      Create your first listing
                    </button>
                  </div>
                ) : (
                  <div className="vendor-listings-grid">
                    {listings.map((listing) => (
                      <VendorListingCard
                        key={listing.id}
                        listing={listing}
                        onApprove={listing.pendingClaimId ? () => handleApproveClaim(listing.pendingClaimId) : null}
                        onReject={listing.pendingClaimId ? () => handleRejectClaim(listing.pendingClaimId) : null}
                        actionError={actionError != null && actionError.claimId === listing.pendingClaimId ? actionError.message : null}
                      />
                    ))}
                  </div>
                )}
              </section>

              <VendorNotificationsPanel
                notifications={notifications}
                socket={socket}
                onNotification={setNotifications}
                onClaimReceived={({ listing_id, claim_id }) =>
                  setListings((prev) =>
                    prev.map((l) =>
                      l.id === listing_id ? { ...l, pendingClaimId: claim_id } : l
                    )
                  )
                }
              />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
