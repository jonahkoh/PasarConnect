export default function FoodCard({
  item,
  onAction,
  isProcessing,
  actionLabel = "Claim",
}) {
  return (
    <article className="food-card">
      <div className="food-card__media">
        <img
          className="food-card__image"
          src={item.imageUrl}
          alt={item.name}
          onError={(e) => {
            e.currentTarget.src =
              "https://via.placeholder.com/600x400?text=Food+Image";
          }}
        />

        <span
          className={`food-card__badge ${
            item.badge === "Charity Priority" ? "badge--blue" : "badge--orange"
          }`}
        >
          {item.badge}
        </span>

        {item.charityWindow && (
          <span className="food-card__window">{item.charityWindow}</span>
        )}
      </div>

      <div className="food-card__content">
        <h3>{item.name}</h3>
        <p className="food-card__vendor">{item.vendor}</p>

        <div className="food-card__meta">
          <span>⌖ {item.distanceKm}km</span>
          <span>🏷 {item.quantityLabel}</span>
        </div>

        <div className="food-card__footer">
          <strong className="food-card__price">{item.priceLabel}</strong>

          <button
            className="claim-btn"
            onClick={() => onAction(item)}
            disabled={isProcessing || item.status !== "AVAILABLE"}
          >
            {isProcessing ? `${actionLabel}ing...` : actionLabel}
          </button>
        </div>
      </div>
    </article>
  );
}