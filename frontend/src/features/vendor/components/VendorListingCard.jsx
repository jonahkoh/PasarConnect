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
          <div className="vendor-action-btns">
            {onApprove && (
              <button
                type="button"
                onClick={onApprove}
                className="vendor-action-btn vendor-action-btn--approve"
              >
                ✓ Approve
              </button>
            )}
            {onReject && (
              <button
                type="button"
                onClick={onReject}
                className="vendor-action-btn vendor-action-btn--reject"
              >
                ✕ Reject
              </button>
            )}
          </div>
        )}

        {actionError && (
          <p role="alert" className="vendor-action-error">{actionError}</p>
        )}
      </div>
    </article>
  );
}
