import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import TopNav from "../components/TopNav";
import FoodCard from "../components/FoodCard";
import CharityFilterSidebar from "../components/CharityFilterSidebar";
import ClaimSummaryCard from "../components/ClaimSummaryCard";
import LiveFoodMap from "../components/LiveFoodMap";
import { submitClaim, postArrive, fetchMyClaims, joinWaitlist, acceptWaitlistOffer, declineWaitlistOffer } from "../lib/claimsApi";

// Must match backend QUEUE_WINDOW_MINUTES=0.5 (30 seconds)
const QUEUE_WINDOW_MS = 0.5 * 60 * 1000;

function parseClaimError(error) {
  // 409 queue-window errors carry structured detail — handle before inspecting the message.
  if (error?.status === 409) {
    const errorCode = error?.detail?.error;
    if (errorCode === "queue_window_active" || errorCode === "queue_exists") {
      return { type: "queue_window", message: error.detail?.message ?? "", detail: error.detail };
    }
  }

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

function isCharityEligible(item) {
  return item.status === "AVAILABLE" && Boolean(item.charityWindow);
}

function isInQueueWindow(item, now) {
  if (!item.listedAt) return false;
  return (now - new Date(item.listedAt).getTime()) < QUEUE_WINDOW_MS;
}

export default function CharityClaimPage({
  listings,
  selectedClaimIds,
  onToggleClaimQueue,
  onRemoveFromClaimQueue,
  onApplyClaimSuccesses,
  isLoading = false,
  socket = null,
  authUser = null,
}) {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [activeView, setActiveView] = useState("queue");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [sortBy, setSortBy] = useState("nearest");
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [selectedCategories, setSelectedCategories] = useState([]);
  const [selectedPickupWindows, setSelectedPickupWindows] = useState([]);
  const [claimHistory, setClaimHistory] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem("claimHistory") || "[]");
    } catch {
      return [];
    }
  });
  const [submissionSummary, setSubmissionSummary] = useState(null);
  const [selectedMapListingId, setSelectedMapListingId] = useState(
    listings.find(isCharityEligible)?.id ?? null
  );
  // Track per-claim arrive submission state to avoid double-clicks.
  const [arrivingClaimId, setArrivingClaimId] = useState(null);

  // Queue-window: items from bulk submit that returned queue_window_active.
  const [queueWindowItems, setQueueWindowItems] = useState([]); // [{ item, detail }]
  const [joiningQueueFor, setJoiningQueueFor] = useState(null); // listing_id currently being joined

  // Offered slots pushed via socket when charity wins the waitlist queue.
  const [offeredListings, setOfferedListings] = useState([]);    // [{ listing_id, message, ... }]
  const [acceptingOfferId, setAcceptingOfferId] = useState(null);
  const [decliningOfferId, setDecliningOfferId] = useState(null);
  // Popup shown briefly after a charity joins the queue (shows their position).
  const [queueJoinedNotice, setQueueJoinedNotice] = useState(null); // { listing_id, name, position }

  // Track which listings this charity has joined the queue for.
  // Shape: { [listing_id]: { status: 'QUEUING' | 'WAITING' | 'OFFERED', position: number|null } }
  // Persisted to sessionStorage so navigating to /charity/:id and back preserves queue state.
  const [joinedWaitlist, setJoinedWaitlist] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem("joinedWaitlist") || "{}"); } catch { return {}; }
  });
  useEffect(() => {
    try { sessionStorage.setItem("joinedWaitlist", JSON.stringify(joinedWaitlist)); } catch {}
  }, [joinedWaitlist]);

  // Live tick — updates every second so queue-window countdowns re-render automatically.
  const [nowMs, setNowMs] = useState(Date.now());
  const tickRef = useRef(null);
  useEffect(() => {
    tickRef.current = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(tickRef.current);
  }, []);

  // Derived: active claims that are still pending collection or awaiting vendor approval.
  const activeClaims = useMemo(
    () => claimHistory.filter(
      (c) => c.claim_id && (c.status === "PENDING_COLLECTION" || c.status === "AWAITING_VENDOR_APPROVAL")
    ),
    [claimHistory]
  );

  function updateClaimStatus(claimId, newStatus) {
    setClaimHistory((prev) => {
      const updated = prev.map((c) => c.claim_id === claimId ? { ...c, status: newStatus } : c);
      try { sessionStorage.setItem("claimHistory", JSON.stringify(updated)); } catch { /* non-fatal */ }
      return updated;
    });
  }

  // Listen for vendor approval / rejection updates on active claims.
  useEffect(() => {
    if (!socket) return;
    function handleCompleted(payload) {
      updateClaimStatus(payload.claim_id, "COMPLETED");
    }
    function handleCancelled(payload) {
      // claim:cancelled fires on vendor reject AND on charity cancel — guard by claim_id
      if (payload.claim_id) updateClaimStatus(payload.claim_id, "CANCELLED");
    }
    socket.on("claim:completed", handleCompleted);
    socket.on("claim:cancelled", handleCancelled);
    return () => {
      socket.off("claim:completed", handleCompleted);
      socket.off("claim:cancelled", handleCancelled);
    };
  }, [socket]);

  // Listen for waitlist slot offers pushed by the notification service.
  useEffect(() => {
    if (!socket) return;
    function handleOffered(payload) {
      setOfferedListings((prev) => {
        // De-dupe: ignore if already showing an offer for this listing.
        if (prev.some((o) => o.listing_id === payload.listing_id)) return prev;
        return [...prev, payload];
      });
      setJoinedWaitlist((prev) =>
        prev[payload.listing_id]
          ? { ...prev, [payload.listing_id]: { ...prev[payload.listing_id], status: "OFFERED" } }
          : prev
      );
    }
    socket.on("claim:offered", handleOffered);
    return () => socket.off("claim:offered", handleOffered);
  }, [socket]);

  // On mount, hydrate claim history from the DB so active claims survive page refresh/re-login.
  // Also updates stale sessionStorage entries (e.g. PENDING_COLLECTION that became COMPLETED).
  useEffect(() => {
    if (!authUser?.token) return;
    fetchMyClaims(authUser.token)
      .then((claims) => {
        if (claims.length === 0) return;
        // Build a map of DB-authoritative status keyed by claim id.
        const dbStatusById = new Map(claims.map((c) => [c.id, c.status]));
        setClaimHistory((prev) => {
          // Step 1: update status of any existing entries whose DB status has changed.
          const updated = prev.map((e) => {
            if (!e.claim_id) return e;
            const dbStatus = dbStatusById.get(e.claim_id);
            return dbStatus && dbStatus !== e.status ? { ...e, status: dbStatus } : e;
          });
          // Step 2: add new active DB claims not yet in history.
          const existingIds = new Set(updated.map((e) => e.claim_id));
          const newEntries = claims
            .filter((c) =>
              !existingIds.has(c.id) &&
              (c.status === "PENDING_COLLECTION" || c.status === "AWAITING_VENDOR_APPROVAL")
            )
            .map((c) => ({
              historyId: `db-${c.id}`,
              id: c.listing_id,
              claim_id: c.id,
              name: `Listing #${c.listing_id}`,
              vendor: "",
              status: c.status,
              claimedAtLabel: new Date(c.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            }));
          if (newEntries.length === 0 && updated.every((e, i) => e === prev[i])) return prev;
          const merged = [...newEntries, ...updated];
          try { sessionStorage.setItem("claimHistory", JSON.stringify(merged)); } catch { /* non-fatal */ }
          return merged;
        });
      })
      .catch(() => { /* non-fatal — banner still shows sessionStorage entries */ });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authUser?.token]);

  async function handleArrive(claim) {
    setArrivingClaimId(claim.claim_id);
    try {
      await postArrive(claim.claim_id, authUser?.token);
      updateClaimStatus(claim.claim_id, "AWAITING_VENDOR_APPROVAL");
    } catch {
      // Arrive failed (e.g. 409 — claim already completed/cancelled by vendor).
      // Re-sync from DB so the banner reflects the true current status.
      if (authUser?.token) {
        fetchMyClaims(authUser.token)
          .then((claims) => {
            const match = claims.find((c) => c.id === claim.claim_id);
            if (match) updateClaimStatus(claim.claim_id, match.status);
          })
          .catch(() => {});
      }
    } finally {
      setArrivingClaimId(null);
    }
  }

  async function handleJoinQueue(listing_id) {
    setJoiningQueueFor(listing_id);
    const item = listings.find((l) => l.id === listing_id);
    try {
      const result = await joinWaitlist({
        listing_id,
        charity_id: Number(authUser?.userId),
        token: authUser?.token,
      });
      // Mark as QUEUING (position assigned after window closes)
      setJoinedWaitlist((prev) => ({
        ...prev,
        [listing_id]: { status: "QUEUING", position: result.position ?? null },
      }));
      // Show queue-joined popup with position info
      setQueueJoinedNotice({
        listing_id,
        name: item?.name ?? `Listing #${listing_id}`,
        position: result.position ?? null,
      });
      // Remove from bulk-submit queue-window list if present
      setQueueWindowItems((prev) => prev.filter((q) => q.item.id !== listing_id));
    } catch {
      // Non-fatal — button stays enabled so charity can retry.
    } finally {
      setJoiningQueueFor(null);
    }
  }

  async function handleAcceptOffer(listing_id) {
    setAcceptingOfferId(listing_id);
    try {
      const claim = await acceptWaitlistOffer({
        listing_id,
        charity_id: Number(authUser?.userId),
        token: authUser?.token,
      });
      setOfferedListings((prev) => prev.filter((o) => o.listing_id !== listing_id));
      setJoinedWaitlist((prev) => { const n = { ...prev }; delete n[listing_id]; return n; });
      const listingName = listings.find((l) => l.id === listing_id)?.name ?? `Listing #${listing_id}`;
      const vendor = listings.find((l) => l.id === listing_id)?.vendor ?? "";
      setClaimHistory((prev) => {
        const entry = {
          historyId: `waitlist-accept-${listing_id}-${Date.now()}`,
          id: listing_id,
          claim_id: claim.id,
          name: listingName,
          vendor,
          status: "PENDING_COLLECTION",
          claimedAtLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        };
        const merged = [entry, ...prev];
        try { sessionStorage.setItem("claimHistory", JSON.stringify(merged.slice(0, 50))); } catch { /* non-fatal */ }
        return merged;
      });
    } catch {
      // Non-fatal — banner stays visible so the charity can retry.
    } finally {
      setAcceptingOfferId(null);
    }
  }

  async function handleDeclineOffer(listing_id) {
    setDecliningOfferId(listing_id);
    try {
      await declineWaitlistOffer({
        listing_id,
        charity_id: Number(authUser?.userId),
        token: authUser?.token,
      });
      setOfferedListings((prev) => prev.filter((o) => o.listing_id !== listing_id));
    } catch {
      // Non-fatal — banner stays visible so the charity can retry.
    } finally {
      setDecliningOfferId(null);
    }
  }

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
    if (!socket || filteredMapListings.length === 0) return;
    filteredMapListings.forEach((item) => {
      socket.emit("subscribe:listing", { listing_id: item.id });
    });
  }, [socket, filteredMapListings]);

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
          const response = await submitClaim({
            listing_id: item.id,
            charity_id: Number(authUser?.userId),
            listing_version: item.version ?? 0,
            token: authUser?.token,
          });
          return {
            item,
            claimId: response.id,
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
      queue_window: 0,
    };

    const successIds = [];
    const historyEntries = [];
    const nextQueueWindowItems = [];

    claimResults.forEach((result) => {
      if (result.status === "fulfilled") {
        nextSummary.success += 1;
        successIds.push(result.value.item.id);
        historyEntries.push({
          historyId: `${result.value.item.id}-${Date.now()}-${historyEntries.length}`,
          id: result.value.item.id,
          claim_id: result.value.claimId,
          name: result.value.item.name,
          vendor: result.value.item.vendor,
          status: "PENDING_COLLECTION",
          claimedAtLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        });
        return;
      }

      if (result.reason.type === "queue_window") {
        nextSummary.queue_window += 1;
        nextQueueWindowItems.push({ item: result.reason.item, detail: result.reason.detail });
      } else {
        nextSummary[result.reason.type] += 1;
      }
    });

    onApplyClaimSuccesses(successIds);
    setClaimHistory((prev) => {
      const merged = [...historyEntries, ...prev];
      try { sessionStorage.setItem("claimHistory", JSON.stringify(merged.slice(0, 50))); } catch { /* non-fatal */ }
      return merged;
    });
    setSubmissionSummary(nextSummary);
    setQueueWindowItems(nextQueueWindowItems);
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



        {activeClaims.map((claim) => (
          <div
            key={claim.claim_id}
            className={`active-claim-banner${claim.status === "AWAITING_VENDOR_APPROVAL" ? " active-claim-banner--waiting" : ""}`}
            role="status"
          >
            <div className="active-claim-banner__info">
              <strong>{claim.name}</strong>
              <span>Vendor: {claim.vendor}</span>
              {claim.status === "AWAITING_VENDOR_APPROVAL" ? (
                <span className="active-claim-banner__status">Waiting for vendor to confirm your arrival…</span>
              ) : (
                <span className="active-claim-banner__status">Ready to collect — head to the vendor and mark your arrival.</span>
              )}
            </div>
            {claim.status === "PENDING_COLLECTION" && (
              <button
                type="button"
                className="landing-button landing-button--primary"
                onClick={() => handleArrive(claim)}
                disabled={arrivingClaimId === claim.claim_id}
              >
                {arrivingClaimId === claim.claim_id ? "Notifying…" : "I've Arrived"}
              </button>
            )}
          </div>
        ))}

        {queueWindowItems.length > 0 && (
          <div className="queue-window-section" role="region" aria-label="Queue window listings">
            <h2 className="queue-window-section__title">Join the Queue</h2>
            <p className="queue-window-section__desc">
              These listings are in their charity queue window. Join now to be considered when the window closes.
            </p>
            {queueWindowItems.map(({ item, detail }) => (
              <div key={item.id} className="queue-window-item">
                <div className="queue-window-item__info">
                  <strong>{item.name}</strong>
                  {detail?.window_closes_at && (
                    <span>Window closes at {new Date(detail.window_closes_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                  )}
                </div>
                <button
                  type="button"
                  className="landing-button landing-button--primary"
                  onClick={() => handleJoinQueue(item.id)}
                  disabled={joiningQueueFor === item.id}
                >
                  {joiningQueueFor === item.id ? "Joining…" : "Join Queue"}
                </button>
              </div>
            ))}
          </div>
        )}

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
                  const inWindow = isInQueueWindow(item, nowMs);
                  const joinedEntry = joinedWaitlist[item.id];

                  // During queue window: show "Join Queue" instead of select/claim.
                  if (inWindow) {
                    const secsLeft = Math.max(0, Math.ceil(
                      (new Date(item.listedAt).getTime() + QUEUE_WINDOW_MS - nowMs) / 1000
                    ));
                    const alreadyJoined = Boolean(joinedEntry);
                    return (
                      <FoodCard
                        key={item.id}
                        item={item}
                        onAction={() => !alreadyJoined && handleJoinQueue(item.id)}
                        onPreview={handlePreviewLocation}
                        onOpenDetail={handleOpenDetail}
                        isProcessing={joiningQueueFor === item.id}
                        isDisabled={alreadyJoined || isSubmitting}
                        actionLabel={alreadyJoined ? "✓ In Queue" : "Join Queue"}
                        helperText={alreadyJoined ? "Position assigned at window close" : `Queue window: ${secsLeft}s left`}
                        cardClassName="food-card--queue-window"
                      />
                    );
                  }

                  // Post-window: if charity joined and is still waiting/offered, show status badge.
                  if (joinedEntry) {
                    const statusLabel = joinedEntry.status === "OFFERED"
                      ? "⭐ Offered — check top of page"
                      : joinedEntry.position != null
                        ? `Queue #${joinedEntry.position}`
                        : "In queue";
                    return (
                      <FoodCard
                        key={item.id}
                        item={item}
                        onAction={() => {}}
                        onPreview={handlePreviewLocation}
                        onOpenDetail={handleOpenDetail}
                        isProcessing={false}
                        isDisabled={true}
                        actionLabel={statusLabel}
                        helperText="Waiting for your turn"
                        cardClassName="food-card--in-queue"
                      />
                    );
                  }

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

      {/* ── Waitlist offer modal ── shown when backend promotes this charity */}
      {offeredListings.length > 0 && (() => {
        const offer = offeredListings[0];
        const listingName = listings.find((l) => l.id === offer.listing_id)?.name ?? `Listing #${offer.listing_id}`;
        return (
          <div className="wl-modal-backdrop" role="dialog" aria-modal="true" aria-label="Slot offered">
            <div className="wl-modal">
              <button
                type="button"
                className="wl-modal__close"
                aria-label="Dismiss"
                onClick={() => setOfferedListings((p) => p.slice(1))}
              >✕</button>
              <p className="wl-modal__eyebrow">Slot Available</p>
              <h2 className="wl-modal__title">{listingName}</h2>
              <p className="wl-modal__body">
                {offer.message ?? "You've been selected from the waitlist! Accept to confirm your claim or decline to pass."}
              </p>
              {offeredListings.length > 1 && (
                <p className="wl-modal__more">{offeredListings.length - 1} more offer(s) pending</p>
              )}
              <div className="wl-modal__actions">
                <button
                  type="button"
                  className="landing-button landing-button--primary"
                  onClick={() => handleAcceptOffer(offer.listing_id)}
                  disabled={acceptingOfferId === offer.listing_id || decliningOfferId === offer.listing_id}
                >
                  {acceptingOfferId === offer.listing_id ? "Accepting…" : "Accept"}
                </button>
                <button
                  type="button"
                  className="landing-button"
                  onClick={() => handleDeclineOffer(offer.listing_id)}
                  disabled={acceptingOfferId === offer.listing_id || decliningOfferId === offer.listing_id}
                >
                  {decliningOfferId === offer.listing_id ? "Declining…" : "Decline"}
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* ── Queue-joined notice ── shows position after joining the waitlist */}
      {queueJoinedNotice && (
        <div className="wl-toast" role="status">
          <button
            type="button"
            className="wl-toast__close"
            aria-label="Dismiss"
            onClick={() => setQueueJoinedNotice(null)}
          >✕</button>
          <p className="wl-toast__title">You joined the queue!</p>
          <p className="wl-toast__body">
            <strong>{queueJoinedNotice.name}</strong>
            {queueJoinedNotice.position != null && queueJoinedNotice.position > 0
              ? ` — you are #${queueJoinedNotice.position} in line. Position is finalised when the window closes.`
              : " — your position will be assigned when the queue window closes."}
          </p>
        </div>
      )}
    </div>
  );
}
