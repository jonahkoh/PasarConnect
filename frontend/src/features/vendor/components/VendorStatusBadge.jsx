const STATUS_LABELS = {
  CHARITY_ONLY: "Charity Only",
  PUBLIC_AVAILABLE: "Public Available",
  PENDING_COLLECTION: "Pending Collection",
  PAYMENT_PENDING: "Payment Pending",
  SOLD: "Sold",
};

const STATUS_CLASSNAMES = {
  CHARITY_ONLY: "vendor-status-badge vendor-status-badge--charity",
  PUBLIC_AVAILABLE: "vendor-status-badge vendor-status-badge--public",
  PENDING_COLLECTION: "vendor-status-badge vendor-status-badge--collection",
  PAYMENT_PENDING: "vendor-status-badge vendor-status-badge--payment",
  SOLD: "vendor-status-badge vendor-status-badge--sold",
};

export default function VendorStatusBadge({ status }) {
  return (
    <span className={STATUS_CLASSNAMES[status] ?? "vendor-status-badge"}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
