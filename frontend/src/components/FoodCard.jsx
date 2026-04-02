export default function FoodCard({
  item,
  onAction,
  onPreview,
  onOpenDetail,
  isProcessing,
  isDisabled = false,
  actionLabel = "Claim",
  helperText = "",
  cardClassName = "",
}) {
  return (
    <article
      className={`food-card ${cardClassName} ${onOpenDetail ? "food-card--interactive" : ""}`.trim()}
      onClick={() => onOpenDetail?.(item)}
      onKeyDown={(event) => {
        if ((event.key === "Enter" || event.key === " ") && onOpenDetail) {
          event.preventDefault();
          onOpenDetail(item);
        }
      }}
      role={onOpenDetail ? "button" : undefined}
      tabIndex={onOpenDetail ? 0 : undefined}
    >
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
            item.badge === "Available" ? "badge--green" : "badge--red"
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
          <div className="food-card__actions">
            <strong className="food-card__price">{item.priceLabel}</strong>
            {helperText && <span className="food-card__helper">{helperText}</span>}
            {onPreview && (
              <div className="food-card__links">
                <button
                  type="button"
                  className="food-card__ghost-link"
                  onClick={(event) => {
                    event.stopPropagation();
                    onPreview(item);
                  }}
                >
                  See location
                </button>
              </div>
            )}
          </div>

          <button
            className="claim-btn"
            onClick={(event) => {
              event.stopPropagation();
              onAction(item);
            }}
            disabled={isProcessing || isDisabled || item.status !== "AVAILABLE"}
          >
            {isProcessing ? `${actionLabel}ing...` : actionLabel}
          </button>
        </div>
      </div>
    </article>
  );
}
