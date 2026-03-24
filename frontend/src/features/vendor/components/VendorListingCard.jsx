import VendorStatusBadge from "./VendorStatusBadge";

export default function VendorListingCard({ listing }) {
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
      </div>
    </article>
  );
}
