import { Link } from "react-router-dom";
import ListingLocationMap from "./ListingLocationMap";

export default function LiveFoodMap({
  listings,
  selectedListingId,
  onSelectListing,
  isLoading = false,
  eyebrow = "Live pickup map",
  title = "Food locations around you",
  subcopy = "Every visible charity listing is roughly plotted here, and you can click any pin or card to inspect where pickup happens.",
  selectedLabel = "Selected listing",
  routeBase = "/charity",
  primaryActionLabel = "Open full listing",
}) {
  const selectedListing =
    listings.find((listing) => listing.id === selectedListingId) ?? listings[0] ?? null;

  return (
    <section className="live-food-map">
      <div className="live-food-map__header">
        <div>
          <p className="live-food-map__eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
          <p className="live-food-map__subcopy">{subcopy}</p>
        </div>

        <div className="live-food-map__status-stack">
          <span className="live-food-map__status live-food-map__status--success">
            {listings.length} visible food pin{listings.length === 1 ? "" : "s"}
          </span>
          <span className="live-food-map__status live-food-map__status--neutral">
            Rough pickup locations
          </span>
        </div>
      </div>

      <div className="live-food-map__layout">
        <div className="live-food-map__canvas">
          {isLoading && (
            <div className="live-food-map__loading-overlay" role="status" aria-live="polite">
              Loading listings…
            </div>
          )}
          <ListingLocationMap
            listings={listings}
            selectedListingId={selectedListing?.id ?? null}
            onSelectListing={onSelectListing}
            showUserLocation
            className="live-food-map__leaflet"
            zoom={13}
          />
        </div>

        <aside className="live-food-map__sidebar">
          {selectedListing ? (
            <article className="live-food-map__focus-card">
              <p className="live-food-map__focus-label">{selectedLabel}</p>
              <h3>{selectedListing.name}</h3>
              <p>{selectedListing.address}</p>
              <div className="live-food-map__focus-meta">
                <span>{selectedListing.vendor}</span>
                <span>{selectedListing.quantityLabel}</span>
                {selectedListing.distanceKm != null && <span>{selectedListing.distanceKm} km away</span>}
              </div>
              <div className="live-food-map__focus-actions">
                <Link to={`${routeBase}/${selectedListing.id}`} className="live-food-map__link-btn">
                  {primaryActionLabel}
                </Link>
                <a
                  href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${selectedListing.latitude},${selectedListing.longitude} (${selectedListing.name})`)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="live-food-map__text-link"
                >
                  Open in Maps
                </a>
              </div>
            </article>
          ) : (
            <div className="live-food-map__empty">
              <strong>No mapped listings match your current filters.</strong>
              <span>Try clearing filters to reveal more food pickup locations.</span>
            </div>
          )}

          <div className="live-food-map__list">
            {listings.map((listing) => {
              const isSelected = listing.id === selectedListing?.id;

              return (
                <button
                  key={listing.id}
                  type="button"
                  className={`live-food-map__list-item ${isSelected ? "live-food-map__list-item--selected" : ""}`.trim()}
                  onClick={() => onSelectListing(listing.id)}
                >
                  <div>
                    <h3>{listing.name}</h3>
                    <p>{listing.address}</p>
                  </div>
                  <div className="live-food-map__list-meta">
                    <span>{listing.quantityLabel}</span>
                    {listing.distanceKm != null && <span>{listing.distanceKm} km away</span>}
                  </div>
                </button>
              );
            })}
          </div>
        </aside>
      </div>
    </section>
  );
}
