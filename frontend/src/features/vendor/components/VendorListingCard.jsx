import VendorStatusBadge from "./VendorStatusBadge";

export default function VendorListingCard({ listing, onApprove, onReject, actionError }) {
  return (
    <article className="vendor-listing-card">
      <div className="vendor-listing-card__media">
        <img
          src={listing.imageUrl}
          alt={listing.name}
          className="vendor-listing-card__image"
        />
      </div>

      <div className="vendor-listing-card__content">
        <div className="vendor-listing-card__header">
          <div>
            <h3>{listing.name}</h3>
            <p>{listing.expiryLabel}</p>
          </div>
          <VendorStatusBadge status={listing.status} />
        </div>

        <dl className="vendor-listing-card__details">
          <div>
            <dt>Quantity</dt>
            <dd>{listing.quantity}</dd>
          </div>
          <div>
            <dt>Pickup</dt>
            <dd>{listing.pickupWindow}</dd>
          </div>
        </dl>

        <p className="vendor-listing-card__updated">{listing.lastUpdatedLabel}</p>

        {(onApprove || onReject) && (
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
            {onApprove && (
              <button
                type="button"
                onClick={onApprove}
                style={{
                  flex: 1, padding: "0.45rem 0", borderRadius: "6px",
                  background: "#27ae60", color: "#fff", border: "none", cursor: "pointer",
                  fontSize: "0.85rem",
                }}
              >
                Approve
              </button>
            )}
            {onReject && (
              <button
                type="button"
                onClick={onReject}
                style={{
                  flex: 1, padding: "0.45rem 0", borderRadius: "6px",
                  background: "#e74c3c", color: "#fff", border: "none", cursor: "pointer",
                  fontSize: "0.85rem",
                }}
              >
                Reject
              </button>
            )}
          </div>
        )}

        {actionError && (
          <p role="alert" style={{ color: "#c0392b", fontSize: "0.8rem", marginTop: "0.4rem" }}>
            {actionError}
          </p>
        )}
      </div>
    </article>
  );
}
