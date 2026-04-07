import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import TopNav from "../components/TopNav";
import { cancelClaim, fetchMyClaims, postArrive } from "../lib/claimsApi";

// Must match backend CANCEL_WINDOW_MINUTES
const CANCEL_WINDOW_MINUTES = 1;

const STATUS_LABEL = {
  PENDING_COLLECTION:      "Ready to collect",
  AWAITING_VENDOR_APPROVAL: "Awaiting vendor confirmation",
  COMPLETED:               "Completed",
  CANCELLED:               "Cancelled",
  NO_SHOW:                 "No-show",
};

const STATUS_CLASS = {
  PENDING_COLLECTION:       "order-status order-status--success",
  AWAITING_VENDOR_APPROVAL: "order-status order-status--pending",
  COMPLETED:                "order-status order-status--collected",
  CANCELLED:                "order-status order-status--refunded",
  NO_SHOW:                  "order-status order-status--forfeited",
};

// Pending-first sort: Ready to collect → Awaiting vendor → everything else.
const CLAIM_SORT_ORDER = {
  PENDING_COLLECTION:       0,
  AWAITING_VENDOR_APPROVAL: 1,
  COMPLETED:                2,
  CANCELLED:                3,
  NO_SHOW:                  4,
};

function sortClaims(list) {
  return [...list].sort((a, b) => {
    const diff = (CLAIM_SORT_ORDER[a.status] ?? 99) - (CLAIM_SORT_ORDER[b.status] ?? 99);
    if (diff !== 0) return diff;
    return new Date(b.created_at || 0) - new Date(a.created_at || 0);
  });
}

function formatDate(isoString) {
  if (!isoString) return "—";
  return new Date(isoString).toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function getRoleLabel(role) {
  if (role === "charity") return "Charity";
  if (role === "public") return "Public User";
  if (role === "vendor") return "Vendor";
  return role ?? "—";
}

export default function ClaimHistoryPage({ authUser, socket }) {
  const [claims, setClaims]     = useState([]);
  const [isLoading, setLoading] = useState(true);
  const [error, setError]       = useState("");
  // Per-claim action state: { [claimId]: "arriving" | "arrived" | "cancelling" | "error:msg" }
  const [actions, setActions]   = useState({});
  const [lateCancelWarning, setLateCancelWarning] = useState(false);

  const userName = sessionStorage.getItem("authUserName") || (authUser?.userId ? `User #${authUser.userId}` : "—");
  const userRole = authUser?.role ?? sessionStorage.getItem("authRole") ?? "—";
  const userId   = authUser?.userId ?? sessionStorage.getItem("authUserId") ?? "—";

  // Load claims from the API, and also merge with sessionStorage for claims not yet in DB.
  useEffect(() => {
    if (!authUser?.token) {
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchMyClaims(authUser.token)
      .then((data) => {
        // Merge DB claims with sessionStorage so local-only entries appear too.
        const sessionClaims = (() => {
          try { return JSON.parse(sessionStorage.getItem("claimHistory") || "[]"); } catch { return []; }
        })();
        const dbIds = new Set(data.map((c) => c.id));
        // Convert DB shape to display shape.
        const dbMapped = data.map((c) => ({
          claim_id:       c.id,
          listing_id:     c.listing_id,
          name:           `Listing #${c.listing_id}`,
          vendor:         c.vendor ?? "",
          status:         c.status,
          created_at:     c.created_at,
        }));
        // Add sessionStorage entries whose claim_id isn't in the DB response.
        const extraSession = sessionClaims
          .filter((s) => s.claim_id && !dbIds.has(s.claim_id))
          .map((s) => ({
            claim_id:   s.claim_id,
            listing_id: s.id,
            name:       s.name,
            vendor:     s.vendor ?? "",
            status:     s.status,
            created_at: null,
          }));
        setClaims([...dbMapped, ...extraSession]);

        // Update sessionStorage pending count for TopNav badge.
        const pending = data.filter(
          (c) => c.status === "PENDING_COLLECTION" || c.status === "AWAITING_VENDOR_APPROVAL"
        ).length;
        try { sessionStorage.setItem("claimPendingCount", String(pending)); } catch {}
      })
      .catch((err) => setError(err.message || "Could not load claim history."))
      .finally(() => setLoading(false));
  }, [authUser]);

  // Real-time status updates from socket.
  useEffect(() => {
    if (!socket) return;

    function patch(claimId, newStatus) {
      setClaims((prev) => prev.map((c) => c.claim_id === claimId ? { ...c, status: newStatus } : c));
      // Recompute pending count for TopNav badge.
      setClaims((prev) => {
        const pending = prev.filter(
          (c) => c.status === "PENDING_COLLECTION" || c.status === "AWAITING_VENDOR_APPROVAL"
        ).length;
        try { sessionStorage.setItem("claimPendingCount", String(pending)); } catch {}
        return prev;
      });
    }

    socket.on("claim:completed",  ({ claim_id }) => patch(claim_id, "COMPLETED"));
    socket.on("claim:cancelled",  ({ claim_id }) => { if (claim_id) patch(claim_id, "CANCELLED"); });

    return () => {
      socket.off("claim:completed");
      socket.off("claim:cancelled");
    };
  }, [socket]);

  async function handleArrive(claim) {
    setActions((prev) => ({ ...prev, [claim.claim_id]: "arriving" }));
    try {
      await postArrive(claim.claim_id, authUser?.token);
      setClaims((prev) =>
        prev.map((c) => c.claim_id === claim.claim_id ? { ...c, status: "AWAITING_VENDOR_APPROVAL" } : c)
      );
      setActions((prev) => ({ ...prev, [claim.claim_id]: "arrived" }));
    } catch (err) {
      setActions((prev) => ({ ...prev, [claim.claim_id]: `error:${err.message || "Failed to signal arrival."}` }));
    }
  }

  async function handleCancel(claim) {
    setActions((prev) => ({ ...prev, [claim.claim_id]: "cancelling" }));
    try {
      const result = await cancelClaim({
        claim_id:   claim.claim_id,
        charity_id: Number(authUser?.userId),
        token:      authUser?.token,
      });
      setClaims((prev) =>
        prev.map((c) => c.claim_id === claim.claim_id ? { ...c, status: "CANCELLED" } : c)
      );
      setActions((prev) => ({ ...prev, [claim.claim_id]: null }));
      if (result?.late_cancel_warning) setLateCancelWarning(true);
    } catch (err) {
      setActions((prev) => ({ ...prev, [claim.claim_id]: `error:${err.message || "Cancel failed."}` }));
    }
  }

  const pendingCount = claims.filter(
    (c) => c.status === "PENDING_COLLECTION" || c.status === "AWAITING_VENDOR_APPROVAL"
  ).length;

  return (
    <div className="app-shell">
      <TopNav authUser={authUser} claimPendingCount={pendingCount} />

      <main className="page history-page">
        {/* ── User profile card ── */}
        <section className="user-profile-card">
          <div className="user-profile-card__avatar" aria-hidden="true">
            {userName.charAt(0).toUpperCase()}
          </div>
          <div className="user-profile-card__info">
            <h2 className="user-profile-card__name">{userName}</h2>
            <div className="user-profile-card__meta">
              <span className="user-profile-card__role-badge">{getRoleLabel(userRole)}</span>
              <span className="user-profile-card__id">ID #{userId}</span>
            </div>
          </div>
          <div className="user-profile-card__stats">
            <div className="user-profile-card__stat">
              <span className="user-profile-card__stat-value">{claims.length}</span>
              <span className="user-profile-card__stat-label">Total Claims</span>
            </div>
            <div className="user-profile-card__stat">
              <span className="user-profile-card__stat-value">{pendingCount}</span>
              <span className="user-profile-card__stat-label">Pending Collection</span>
            </div>
            <div className="user-profile-card__stat">
              <span className="user-profile-card__stat-value">
                {claims.filter((c) => c.status === "COMPLETED").length}
              </span>
              <span className="user-profile-card__stat-label">Completed</span>
            </div>
          </div>
        </section>

        {/* ── History header ── */}
        <section className="history-page__header">
          <div>
            <p className="cart-page__eyebrow">Charity</p>
            <h1>Claim History</h1>
            <p>Track your claims and signal arrival when you are at the vendor.</p>
          </div>
          <Link to="/charity" className="landing-button landing-button--secondary history-page__back">
            ← Browse Listings
          </Link>
        </section>

        {!authUser?.token && (
          <div className="empty-state">
            <Link to="/login">Log in</Link> to view your claim history.
          </div>
        )}

        {authUser?.token && isLoading && (
          <div className="empty-state">Loading your claims…</div>
        )}

        {authUser?.token && !isLoading && error && (
          <div className="alert-error"><strong>Error:</strong> {error}</div>
        )}

        {authUser?.token && !isLoading && !error && claims.length === 0 && (
          <div className="empty-state">
            No claims yet. <Link to="/charity">Browse charity listings</Link>.
          </div>
        )}

        {authUser?.token && !isLoading && !error && claims.length > 0 && (
          <div className="order-history-list">
            {sortClaims(claims).map((claim) => {
              const actionState  = actions[claim.claim_id];
              const isArriving   = actionState === "arriving";
              const hasSentArrival = actionState === "arrived";
              const isCancelling = actionState === "cancelling";
              const actionErr    = typeof actionState === "string" && actionState.startsWith("error:")
                ? actionState.slice(6)
                : null;
              const canActOnClaim =
                claim.status === "PENDING_COLLECTION" || claim.status === "AWAITING_VENDOR_APPROVAL";

              return (
                <article key={claim.claim_id} className="order-card">
                  <div className="order-card__header">
                    <div>
                      <p className="order-card__listing">{claim.name}</p>
                      {claim.vendor && (
                        <p className="order-card__id">Vendor: {claim.vendor}</p>
                      )}
                    </div>
                    <span className={STATUS_CLASS[claim.status] ?? "order-status"}>
                      {STATUS_LABEL[claim.status] ?? claim.status}
                    </span>
                  </div>

                  <div className="order-card__meta">
                    <span><strong>Claim ID:</strong> #{claim.claim_id}</span>
                    {claim.created_at && (
                      <span><strong>Claimed:</strong> {formatDate(claim.created_at)}</span>
                    )}
                  </div>

                  {/* ── Arrival + cancel actions (only active claims) ── */}
                  {canActOnClaim && (
                    <div className="order-card__actions">
                      {claim.status === "PENDING_COLLECTION" && (
                        <>
                          {hasSentArrival ? (
                            <p className="order-card__arrival-sent">
                              Vendor notified — waiting for confirmation.
                            </p>
                          ) : (
                            <button
                              type="button"
                              className="landing-button landing-button--primary"
                              onClick={() => handleArrive(claim)}
                              disabled={isArriving || isCancelling}
                            >
                              {isArriving ? "Notifying vendor…" : "I've Arrived"}
                            </button>
                          )}

                          {!hasSentArrival && (
                            <button
                              type="button"
                              className="btn-cancel-danger"
                              onClick={() => handleCancel(claim)}
                              disabled={isArriving || isCancelling}
                            >
                              {isCancelling ? "Cancelling…" : "Cancel Claim"}
                            </button>
                          )}
                        </>
                      )}

                      {claim.status === "AWAITING_VENDOR_APPROVAL" && (
                        <p className="order-card__arrival-sent">
                          Waiting for vendor to confirm your arrival…
                        </p>
                      )}
                    </div>
                  )}

                  {actionErr && (
                    <p className="order-card__error" role="alert">{actionErr}</p>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </main>

      {/* ── Late-cancel warning toast ── */}
      {lateCancelWarning && (
        <div className="wl-toast wl-toast--warning" role="alert">
          <button
            type="button"
            className="wl-toast__close"
            aria-label="Dismiss"
            onClick={() => setLateCancelWarning(false)}
          >✕</button>
          <p className="wl-toast__title">Late Cancellation Warning</p>
          <p className="wl-toast__body">
            Your claim was cancelled after the {CANCEL_WINDOW_MINUTES}-minute grace period.
            This has been recorded on your account. Repeated late cancellations may affect your standing.
          </p>
        </div>
      )}
    </div>
  );
}
