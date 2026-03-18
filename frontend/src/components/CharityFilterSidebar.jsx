const categoryOptions = [
  "Fresh Produce",
  "Fruit",
  "Bakery",
  "Prepared Meals",
  "Dairy & Soy",
];

const pickupOptions = ["Under 15 mins", "Under 30 mins", "Flexible"];

export default function CharityFilterSidebar({
  selectedCategories,
  selectedPickupWindows,
  onToggleCategory,
  onTogglePickupWindow,
  onClearAll,
  isMobileOpen = false,
  onCloseMobile,
}) {
  return (
    <>
      {isMobileOpen && (
        <button
          className="filters-overlay"
          type="button"
          onClick={onCloseMobile}
          aria-label="Close filters"
        />
      )}

      <aside
        className={`filter-sidebar ${
          isMobileOpen ? "filter-sidebar--mobile-open" : ""
        }`}
      >
        <div className="filter-sidebar__header">
          <h2>Filters</h2>
          <button
            type="button"
            className="filter-sidebar__clear"
            onClick={onClearAll}
          >
            Clear all
          </button>
        </div>

        <div className="filter-group">
          <h3>Category</h3>
          {categoryOptions.map((option) => (
            <label key={option} className="filter-checkbox">
              <input
                type="checkbox"
                checked={selectedCategories.includes(option)}
                onChange={() => onToggleCategory(option)}
              />
              <span>{option}</span>
            </label>
          ))}
        </div>


        <div className="filter-group">
          <h3>Pickup Window</h3>
          <div className="filter-chip-group">
            {pickupOptions.map((option) => {
              const active = selectedPickupWindows.includes(option);

              return (
                <button
                  key={option}
                  type="button"
                  className={`filter-chip ${active ? "filter-chip--active" : ""}`}
                  onClick={() => onTogglePickupWindow(option)}
                >
                  {option}
                </button>
              );
            })}
          </div>
        </div>
      </aside>
    </>
  );
}
