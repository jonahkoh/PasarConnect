import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import TopNav from "../components/TopNav";
import FoodCard from "../components/FoodCard";
import CharityFilterSidebar from "../components/CharityFilterSidebar";
import ClaimSummaryCard from "../components/ClaimSummaryCard";
import LiveFoodMap from "../components/LiveFoodMap";

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseClaimError(error) {
  const rawMessage =
    error?.backendMessage ??
    error?.response?.data?.message ??
    error?.message ??
    "";

  const normalizedMessage = rawMessage.toLowerCase();

  if (normalizedMessage.includes("already claimed")) {
    return {
      type: "conflict",
      message: rawMessage || "Already claimed by another charity",
    };
  }

  if (
    normalizedMessage.includes("eligibility") ||
    normalizedMessage.includes("claim limit")
  ) {
    return {
      type: "eligibility",
      message: rawMessage || "Eligibility check failed",
    };
  }

  if (normalizedMessage.includes("limit reached")) {
    return {
      type: "eligibility",
      message: rawMessage || "Claim limit reached",
    };
  }

  return {
    type: "unavailable",
    message: rawMessage || "No longer available",
  };
}

async function submitClaimAttempt(item) {
  // No live charity-claim API endpoint is wired into the frontend yet,
  // so the current flow uses a mock async attempt that preserves the
  // per-item Promise.allSettled() submission shape.
  await wait(250);

  if (item.status !== "AVAILABLE") {
    throw new Error("No longer available");
  }

  if (item.mockClaimOutcome === "CONFLICT") {
    throw new Error("Already claimed by another charity");
  }

  if (item.mockClaimOutcome === "ELIGIBILITY_FAILURE") {
    throw new Error("Eligibility check failed");
  }

  if (item.mockClaimOutcome === "LIMIT_REACHED") {
    throw new Error("Claim limit reached");
  }

  if (item.mockClaimOutcome === "UNAVAILABLE") {
    throw new Error("No longer available");
  }

  return {
    itemId: item.id,
    status: "PENDING COLLECTION",
  };
}

function isCharityEligible(item) {
  return item.status === "AVAILABLE" && Boolean(item.charityWindow);
}

export default function CharityClaimPage({
  listings,
  selectedClaimIds,
  onToggleClaimQueue,
  onRemoveFromClaimQueue,
  onApplyClaimSuccesses,
  isLoading = false,
}) {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [activeView, setActiveView] = useState("queue");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [sortBy, setSortBy] = useState("nearest");
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [selectedCategories, setSelectedCategories] = useState([]);
  const [selectedPickupWindows, setSelectedPickupWindows] = useState([]);
  const [claimHistory, setClaimHistory] = useState([]);
  const [submissionSummary, setSubmissionSummary] = useState(null);
  const [selectedMapListingId, setSelectedMapListingId] = useState(
    listings.find(isCharityEligible)?.id ?? null
  );

  function toggleValue(setter, currentValues, value) {
    setter(
      currentValues.includes(value)
        ? currentValues.filter((item) => item !== value)
        : [...currentValues, value]
    );
  }

  function clearAllFilters() {
    setSelectedCategories([]);
    setSelectedPickupWindows([]);
  }

  const filteredListings = useMemo(() => {
    let result = listings.filter(isCharityEligible);
    const keyword = search.trim().toLowerCase();

    if (keyword) {
      result = result.filter((item) =>
        [item.name, item.vendor, item.category].some((value) =>
          value.toLowerCase().includes(keyword)
        )
      );
    }

    if (selectedCategories.length > 0) {
      result = result.filter((item) => selectedCategories.includes(item.category));
    }

    if (selectedPickupWindows.length > 0) {
      result = result.filter((item) =>
        selectedPickupWindows.includes(item.pickupWindow)
      );
    }

    if (sortBy === "nearest") {
      result.sort((a, b) => a.distanceKm - b.distanceKm);
    } else if (sortBy === "name") {
      result.sort((a, b) => a.name.localeCompare(b.name));
    }

    return result;
  }, [listings, search, selectedCategories, selectedPickupWindows, sortBy]);

  const filteredMapListings = useMemo(
    () => filteredListings.filter((item) => typeof item.latitude === "number" && typeof item.longitude === "number"),
    [filteredListings]
  );

  useEffect(() => {
    if (filteredMapListings.some((item) => item.id === selectedMapListingId)) {
      return;
    }

    setSelectedMapListingId(filteredMapListings[0]?.id ?? null);
  }, [filteredMapListings, selectedMapListingId]);

  function handlePreviewLocation(item) {
    setSelectedMapListingId(item.id);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const queuedIds = useMemo(
    () => new Set(selectedClaimIds),
    [selectedClaimIds]
  );
  const selectedItems = useMemo(
    () => listings.filter((item) => selectedClaimIds.includes(item.id)),
    [listings, selectedClaimIds]
  );

  async function handleToggleSelection(item) {
    setSubmissionSummary(null);
    if (queuedIds.has(item.id)) {
      onRemoveFromClaimQueue(item.id);
      return;
    }

    onToggleClaimQueue(item.id);
  }

  function handleOpenDetail(item) {
    navigate(`/charity/${item.id}`);
  }

  async function handleSubmitClaims() {
    if (selectedItems.length === 0) {
      return;
    }

    setIsSubmitting(true);
    setSubmissionSummary(null);

    const claimResults = await Promise.allSettled(
      selectedItems.map(async (item) => {
        try {
          const response = await submitClaimAttempt(item);
          return {
            item,
            status: response.status,
            outcome: "success",
          };
        } catch (error) {
          const parsedError = parseClaimError(error);
          return Promise.reject({
            item,
            ...parsedError,
          });
        }
      })
    );

    const nextSummary = {
      success: 0,
      conflict: 0,
      eligibility: 0,
      unavailable: 0,
    };

    const successIds = [];
    const historyEntries = [];

    claimResults.forEach((result) => {
      if (result.status === "fulfilled") {
        nextSummary.success += 1;
        successIds.push(result.value.item.id);
        historyEntries.push({
          historyId: `${result.value.item.id}-${Date.now()}-${historyEntries.length}`,
          id: result.value.item.id,
          name: result.value.item.name,
          vendor: result.value.item.vendor,
          status: result.value.status,
          claimedAtLabel: "Submitted just now",
        });
        return;
      }

      nextSummary[result.reason.type] += 1;
    });

    onApplyClaimSuccesses(successIds);
    setClaimHistory((prev) => [...historyEntries, ...prev]);
    setSubmissionSummary(nextSummary);
    setIsSubmitting(false);
    setActiveView("queue");
  }

  return (
    <div className="app-shell">
      <TopNav />

      <main className="catalog-page">
        <div className="catalog-page__intro">
          <h1>Available Food Near You</h1>
          <p>
            Queue charity-eligible items for your organization and submit claims
            individually in real time.
          </p>
        </div>

        <LiveFoodMap
          listings={filteredMapListings}
          selectedListingId={selectedMapListingId}
          onSelectListing={setSelectedMapListingId}
          isLoading={isLoading}
        />

        <section className="marketplace-dashboard">
          <CharityFilterSidebar
            selectedCategories={selectedCategories}
            selectedPickupWindows={selectedPickupWindows}
            onToggleCategory={(value) =>
              toggleValue(setSelectedCategories, selectedCategories, value)
            }
            onTogglePickupWindow={(value) =>
              toggleValue(setSelectedPickupWindows, selectedPickupWindows, value)
            }
            onClearAll={clearAllFilters}
            isMobileOpen={mobileFiltersOpen}
            onCloseMobile={() => setMobileFiltersOpen(false)}
          />

          <section className="catalog-content">
            <div className="catalog-toolbar catalog-toolbar--mobile">
              <button
                type="button"
                className="filters-btn"
                onClick={() => setMobileFiltersOpen(true)}
              >
                Filters
              </button>
            </div>

            <div className="catalog-toolbar">
              <div className="catalog-search">
                <span className="catalog-search__icon">⌕</span>
                <input
                  type="text"
                  placeholder="Search food items..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>

              <select
                className="catalog-sort"
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
              >
                <option value="nearest">Nearest</option>
                <option value="name">A-Z</option>
              </select>
            </div>

            {isLoading ? (
              <div className="empty-state" aria-live="polite">Loading available listings…</div>
            ) : filteredListings.length === 0 ? (
              <div className="empty-state">No charity-eligible food items found.</div>
            ) : (
              <section className="catalog-grid">
                {filteredListings.map((item) => {
                  const isQueued = queuedIds.has(item.id);

                  return (
                    <FoodCard
                      key={item.id}
                      item={item}
                      onAction={handleToggleSelection}
                      onPreview={handlePreviewLocation}
                      onOpenDetail={handleOpenDetail}
                      isProcessing={false}
                      isDisabled={isSubmitting}
                      actionLabel={isQueued ? "Remove" : "Select"}
                      helperText={item.pickupWindow}
                      cardClassName={isQueued ? "food-card--selected" : ""}
                    />
                  );
                })}
              </section>
            )}
          </section>

          <ClaimSummaryCard
            activeView={activeView}
            selectedItems={selectedItems}
            claimHistory={claimHistory}
            submissionSummary={submissionSummary}
            isSubmitting={isSubmitting}
            onChangeView={setActiveView}
            onRemoveItem={onRemoveFromClaimQueue}
            onSubmitClaims={handleSubmitClaims}
          />
        </section>
      </main>
    </div>
  );
}
