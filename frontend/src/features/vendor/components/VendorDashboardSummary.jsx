function countByStatus(listings, status) {
  return listings.filter((item) => item.status === status).length;
}

export default function VendorDashboardSummary({ listings }) {
  const summaryCards = [
    {
      id: "active",
      label: "Active Listings",
      value: listings.filter((item) => item.status !== "SOLD").length,
    },
    {
      id: "charity",
      label: "Charity Only",
      value: countByStatus(listings, "CHARITY_ONLY"),
    },
    {
      id: "public",
      label: "Public Tier",
      value: countByStatus(listings, "PUBLIC_AVAILABLE"),
    },
    {
      id: "attention",
      label: "Needs Attention",
      value:
        countByStatus(listings, "PAYMENT_PENDING") +
        countByStatus(listings, "PENDING_COLLECTION"),
    },
  ];

  return (
    <section className="vendor-summary-grid" aria-label="Vendor dashboard summary">
      {summaryCards.map((card) => (
        <article key={card.id} className="vendor-summary-card">
          <span className="vendor-summary-card__label">{card.label}</span>
          <strong className="vendor-summary-card__value">{card.value}</strong>
        </article>
      ))}
    </section>
  );
}
