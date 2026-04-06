import TopNav from "../../../components/TopNav";
import VendorDashboardSummary from "../components/VendorDashboardSummary";
import VendorListingCard from "../components/VendorListingCard";
import VendorNotificationsPanel from "../components/VendorNotificationsPanel";
import { useVendorDashboard } from "../hooks/useVendorDashboard";

export default function VendorDashboardPage() {
  const { listings, notifications, isLoading, error } = useVendorDashboard();

  return (
    <div className="app-shell">
      <TopNav />

      <main className="page vendor-page">
        <section className="vendor-hero">
          <div>
            <p className="vendor-eyebrow">Vendor Console</p>
            <h1>Track surplus food listings from one place.</h1>
            <p className="vendor-hero__copy">
              Start with a dashboard that makes the charity-to-public lifecycle
              obvious during demos. Listing creation, S3 upload, and compliance
              handling can sit on top of this module next.
            </p>
          </div>
        </section>

        {isLoading ? (
          <div className="empty-state">Loading vendor dashboard...</div>
        ) : error ? (
          <div className="vendor-error-banner" role="alert">
            {error}
          </div>
        ) : (
          <>
            <VendorDashboardSummary listings={listings} />

            <section className="vendor-dashboard-layout">
              <section className="vendor-listings-section">
                <div className="vendor-panel__header">
                  <div>
                    <h2>Current Listings</h2>
                    <p>
                      Inventory Service should remain the source of truth for these
                      records.
                    </p>
                  </div>
                </div>

                {listings.length === 0 ? (
                  <div className="empty-state">
                    No active listings yet. Create your first surplus listing next.
                  </div>
                ) : (
                  <div className="vendor-listings-grid">
                    {listings.map((listing) => (
                      <VendorListingCard key={listing.id} listing={listing} />
                    ))}
                  </div>
                )}
              </section>

              <VendorNotificationsPanel notifications={notifications} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
