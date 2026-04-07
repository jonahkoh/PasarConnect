import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchMyClaims } from "../lib/claimsApi";
import { fetchPurchaseHistory } from "../lib/paymentApi";

function NavLink({ to, children }) {
  return (
    <Link to={to} className="topbar__link">
      {children}
    </Link>
  );
}

function BadgeNavLink({ to, count, children }) {
  return (
    <Link to={to} className="topbar__link topbar__link--badge">
      {children}
      {count > 0 && <span className="topbar__badge">{count}</span>}
    </Link>
  );
}

export default function TopNav({ authUser = null, claimPendingCount, orderPendingCount }) {
  // Use the passed authUser prop first; fall back to sessionStorage so every
  // page (including those that don't thread authUser down) shows the correct nav.
  const role =
    authUser?.role ??
    sessionStorage.getItem("authRole") ??
    null;

  const userId =
    authUser?.userId ??
    sessionStorage.getItem("authUserId") ??
    null;

  // Reactive counts — initialise from sessionStorage so any previously cached
  // value is shown immediately, then refresh from the API on mount so the badge
  // is correct right after login (before the history page has ever been visited).
  const [fetchedClaimCount, setFetchedClaimCount] = useState(
    () => parseInt(sessionStorage.getItem("claimPendingCount") || "0", 10)
  );
  const [fetchedOrderCount, setFetchedOrderCount] = useState(
    () => parseInt(sessionStorage.getItem("orderPendingCount") || "0", 10)
  );

  useEffect(() => {
    const token = authUser?.token ?? sessionStorage.getItem("authToken");
    if (!token || !role) return;

    if (role === "charity") {
      fetchMyClaims(token)
        .then((data) => {
          const count = data.filter(
            (c) => c.status === "PENDING_COLLECTION" || c.status === "AWAITING_VENDOR_APPROVAL"
          ).length;
          sessionStorage.setItem("claimPendingCount", String(count));
          setFetchedClaimCount(count);
        })
        .catch(() => {});
    }

    if (role === "public") {
      fetchPurchaseHistory(token)
        .then((data) => {
          const count = data.filter((o) => o.status === "SUCCESS").length;
          sessionStorage.setItem("orderPendingCount", String(count));
          setFetchedOrderCount(count);
        })
        .catch(() => {});
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleLogout() {
    sessionStorage.removeItem("authToken");
    sessionStorage.removeItem("authRole");
    sessionStorage.removeItem("authUserId");
    sessionStorage.removeItem("authUserName");
    sessionStorage.removeItem("claimPendingCount");
    sessionStorage.removeItem("orderPendingCount");
    // Full-page navigate so App re-reads sessionStorage and clears authUser state.
    window.location.href = "/";
  }

  // Derive a display name: stored at login or fall back to the userId label.
  const displayName =
    sessionStorage.getItem("authUserName") ||
    (userId ? `User #${userId}` : null);

  // Props take priority over the locally-fetched value (history pages pass live counts).
  const resolvedClaimCount = claimPendingCount ?? fetchedClaimCount;
  const resolvedOrderCount = orderPendingCount ?? fetchedOrderCount;

  return (
    <header className="topbar">
      <a href="/#home" className="brand">
        <img
          src="/pasarconnect-logo.svg"
          alt="PasarConnect"
          className="brand__logo"
        />
        <span className="brand__text">PasarConnect</span>
      </a>

      {/* Navigation links — vary by role */}
      {!role && (
        <nav className="topbar__nav" aria-label="Primary navigation">
          <a href="/#home" className="topbar__link">Home</a>
          <a href="/#how-it-works" className="topbar__link">How It Works</a>
          <a href="/#impact" className="topbar__link">Impact</a>
        </nav>
      )}

      {role === "vendor" && (
        <nav className="topbar__nav" aria-label="Vendor navigation">
          <NavLink to="/vendor">Listings</NavLink>
          <NavLink to="/live-chats">Live Chats</NavLink>
          <NavLink to="/vendor/history">Past Listings &amp; Profit</NavLink>
        </nav>
      )}

      {role === "charity" && (
        <nav className="topbar__nav" aria-label="Charity navigation">
          <NavLink to="/charity">Marketplace</NavLink>
          <NavLink to="/live-chats">Live Chats</NavLink>
          <BadgeNavLink
            to="/charity/history"
            count={resolvedClaimCount}
          >
            Claim History
          </BadgeNavLink>
        </nav>
      )}

      {role === "public" && (
        <nav className="topbar__nav" aria-label="Public user navigation">
          <NavLink to="/marketplace">Marketplace</NavLink>
          <NavLink to="/live-chats">Live Chats</NavLink>
          <BadgeNavLink
            to="/marketplace/orders"
            count={resolvedOrderCount}
          >
            Order History
          </BadgeNavLink>
        </nav>
      )}

      <div className="topbar__actions">
        {!role ? (
          <>
            <Link to="/register" className="topbar__register">Register</Link>
            <Link to="/login" className="topbar__login">Login</Link>
          </>
        ) : (
          <div className="topbar__user-group">
            {displayName && (
              <span className="topbar__username">{displayName}</span>
            )}
            <button
              type="button"
              className="topbar__logout"
              onClick={handleLogout}
            >
              Log Out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
