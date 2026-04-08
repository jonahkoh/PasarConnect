import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import TopNav from "../components/TopNav";
import Toast from "../components/Toast";
import { cancelPayment, fetchPurchaseHistory, reportArrived } from "../lib/paymentApi";

function formatCurrency(amount) {
  return new Intl.NumberFormat("en-SG", { style: "currency", currency: "SGD" }).format(amount);
}

function formatDate(isoString) {
  if (!isoString) return "—";
  return new Date(isoString).toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

const STATUS_LABEL = {
  PENDING:              "Reserved",
  SUCCESS:              "Paid — Awaiting Collection",
  COLLECTED:            "Collected",
  REFUNDED:             "Refunded",
  FAILED:               "Failed",
  FORFEITED:            "Forfeited",
};

const STATUS_CLASS = {
  PENDING:   "order-status order-status--pending",
  SUCCESS:   "order-status order-status--success",
  COLLECTED: "order-status order-status--collected",
  REFUNDED:  "order-status order-status--refunded",
  FAILED:    "order-status order-status--failed",
  FORFEITED: "order-status order-status--forfeited",
};

// Pending-first sort: Paid (awaiting collection) → Reserved → everything else.
const ORDER_SORT_PRIORITY = {
  SUCCESS:   0,
  PENDING:   1,
  COLLECTED: 2,
  REFUNDED:  3,
  FAILED:    4,
  FORFEITED: 5,
};

function sortOrders(list) {
  return [...list].sort((a, b) => {
    const diff = (ORDER_SORT_PRIORITY[a.status] ?? 99) - (ORDER_SORT_PRIORITY[b.status] ?? 99);
    if (diff !== 0) return diff;
    return new Date(b.created_at || 0) - new Date(a.created_at || 0);
  });
}

export default function PurchaseHistoryPage({ authUser, socket }) {
  const [orders, setOrders]     = useState([]);
  const [isLoading, setLoading] = useState(true);
  const [error, setError]       = useState("");
  // Per-order action state: { [transactionId]: "arriving" | "cancelling" | "error:message" }
  const [actions, setActions]   = useState({});
  const [toast, setToast]       = useState(null);

  function showToast(msg) {
    setToast(msg);
    setTimeout(() => setToast(null), 6000);
  }

  const userName = sessionStorage.getItem("authUserName") || (authUser?.userId ? `User #${authUser.userId}` : "—");
  const userRole = authUser?.role ?? sessionStorage.getItem("authRole") ?? "—";
  const userId   = authUser?.userId ?? sessionStorage.getItem("authUserId") ?? "—";

  useEffect(() => {
    if (!authUser?.token) {
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchPurchaseHistory(authUser.token)
      .then((data) => {
        setOrders(data);
        const pending = data.filter((o) => o.status === "SUCCESS").length;
        try { sessionStorage.setItem("orderPendingCount", String(pending)); } catch {}
      })
      .catch((err) => setError(err.message || "Could not load order history."))
      .finally(() => setLoading(false));
  }, [authUser]);

  // Listen for real-time updates so status badges refresh without page reload.
  useEffect(() => {
    if (!socket) return;

    function patchOrder(transactionId, newStatus) {
      setOrders((prev) =>
        prev.map((o) =>
          o.transaction_id === transactionId ? { ...o, status: newStatus } : o
        )
      );
    }

    socket.on("payment:collected",  ({ transaction_id }) => {
      patchOrder(transaction_id, "COLLECTED");
      showToast("Item collected. Thank you!");
    });
    socket.on("payment:refunded",   ({ transaction_id, reason }) => {
      patchOrder(transaction_id, "REFUNDED");
      showToast(`Payment Refunded. Reason: ${reason || "Payment has been reversed."}`);
    });
    socket.on("payment:cancelled",  ({ transaction_id }) => {
      patchOrder(transaction_id, "REFUNDED");
      showToast("Payment Refunded. Reason: Order cancelled successfully.");
    });
    socket.on("payment:forfeited",  ({ transaction_id }) => {
      patchOrder(transaction_id, "FORFEITED");
      showToast("Payment Forfeited. Reason: Cancel window expired or no-show recorded.");
    });

    return () => {
      socket.off("payment:collected");
      socket.off("payment:refunded");
      socket.off("payment:cancelled");
      socket.off("payment:forfeited");
    };
  }, [socket]);

  async function handleArrived(transactionId) {
    setActions((prev) => ({ ...prev, [transactionId]: "arriving" }));
    try {
      await reportArrived(transactionId, authUser.token);
      setActions((prev) => ({ ...prev, [transactionId]: "arrived" }));
    } catch (err) {
      setActions((prev) => ({
        ...prev,
        [transactionId]: `error:${err.message || "Failed to signal arrival."}`,
      }));
    }
  }

  async function handleCancel(transactionId) {
    setActions((prev) => ({ ...prev, [transactionId]: "cancelling" }));
    try {
      await cancelPayment(transactionId, Number(authUser.userId), authUser.token);
      setOrders((prev) =>
        prev.map((o) =>
          o.transaction_id === transactionId ? { ...o, status: "REFUNDED" } : o
        )
      );
      setActions((prev) => ({ ...prev, [transactionId]: null }));
    } catch (err) {
      const detail = err.body?.detail;
      const msg =
        (typeof detail === "object" && detail?.message) ||
        (typeof detail === "string" && detail) ||
        err.message ||
        "Cancel failed.";
      setActions((prev) => ({ ...prev, [transactionId]: `error:${msg}` }));
    }
  }

  return (
    <div className="app-shell">
      <TopNav orderPendingCount={orders.filter((o) => o.status === "SUCCESS").length} />
      <Toast message={toast} onDismiss={() => setToast(null)} />

      <main className="page history-page">
        {/* ── User profile card ── */}
        <section className="user-profile-card">
          <div className="user-profile-card__avatar" aria-hidden="true">
            {userName.charAt(0).toUpperCase()}
          </div>
          <div className="user-profile-card__info">
            <h2 className="user-profile-card__name">{userName}</h2>
            <div className="user-profile-card__meta">
              <span className="user-profile-card__role-badge">
                {userRole === "public" ? "Public User" : userRole === "vendor" ? "Vendor" : userRole === "charity" ? "Charity" : (userRole ?? "—")}
              </span>
              <span className="user-profile-card__id">ID #{userId}</span>
            </div>
          </div>
          <div className="user-profile-card__stats">
            <div className="user-profile-card__stat">
              <span className="user-profile-card__stat-value">{orders.length}</span>
              <span className="user-profile-card__stat-label">Total Orders</span>
            </div>
            <div className="user-profile-card__stat">
              <span className="user-profile-card__stat-value">{orders.filter((o) => o.status === "SUCCESS").length}</span>
              <span className="user-profile-card__stat-label">Awaiting Collection</span>
            </div>
            <div className="user-profile-card__stat">
              <span className="user-profile-card__stat-value">{orders.filter((o) => o.status === "COLLECTED").length}</span>
              <span className="user-profile-card__stat-label">Collected</span>
            </div>
          </div>
        </section>

        {/* ── History header ── */}
        <section className="history-page__header">
          <div>
            <p className="cart-page__eyebrow">My Orders</p>
            <h1>Purchase history</h1>
            <p>Track your marketplace purchases and signal when you have arrived for pickup.</p>
          </div>
          <Link to="/marketplace" className="landing-button landing-button--secondary history-page__back">
            ← Browse Marketplace
          </Link>
        </section>

        {!authUser?.token && (
          <div className="empty-state">
            <Link to="/login">Log in</Link> to view your order history.
          </div>
        )}

        {authUser?.token && isLoading && (
          <div className="empty-state">Loading your orders…</div>
        )}

        {authUser?.token && !isLoading && error && (
          <div className="alert-error"><strong>Error:</strong> {error}</div>
        )}

        {authUser?.token && !isLoading && !error && orders.length === 0 && (
          <div className="empty-state">
            No orders yet. <Link to="/marketplace">Browse the marketplace</Link>.
          </div>
        )}

        {authUser?.token && !isLoading && !error && orders.length > 0 && (
          <div className="order-history-list">
            {sortOrders(orders).map((order) => {
              const actionState = actions[order.transaction_id];
              const isArriving  = actionState === "arriving";
              const hasSentArrival = actionState === "arrived";
              const isCancelling = actionState === "cancelling";
              const actionErr   = typeof actionState === "string" && actionState.startsWith("error:")
                ? actionState.slice(6)
                : null;

              return (
                <article key={order.transaction_id} className="order-card">
                  <div className="order-card__header">
                    <div>
                      <p className="order-card__listing">Listing #{order.listing_id}</p>
                      <p className="order-card__id" title={order.transaction_id}>
                        Ref: {order.transaction_id.slice(0, 20)}…
                      </p>
                    </div>
                    <span className={STATUS_CLASS[order.status] ?? "order-status"}>
                      {STATUS_LABEL[order.status] ?? order.status}
                    </span>
                  </div>

                  <div className="order-card__meta">
                    <span><strong>Amount:</strong> {formatCurrency(order.amount)}</span>
                    <span><strong>Ordered:</strong> {formatDate(order.created_at)}</span>
                    {order.updated_at && (
                      <span><strong>Updated:</strong> {formatDate(order.updated_at)}</span>
                    )}
                  </div>

                  {/* ── Arrival banner — only for SUCCESS (paid, awaiting collection) ── */}
                  {order.status === "SUCCESS" && (
                    <div className="order-card__actions">
                      {hasSentArrival ? (
                        <p className="order-card__arrival-sent">
                          Vendor notified — please wait for confirmation.
                        </p>
                      ) : (
                        <button
                          type="button"
                          className="landing-button landing-button--primary"
                          onClick={() => handleArrived(order.transaction_id)}
                          disabled={isArriving}
                        >
                          {isArriving ? "Notifying vendor…" : "I have arrived"}
                        </button>
                      )}

                      <button
                        type="button"
                        className="btn-cancel-danger"
                        onClick={() => handleCancel(order.transaction_id)}
                        disabled={isCancelling || hasSentArrival}
                      >
                        {isCancelling ? "Cancelling…" : "Cancel order"}
                      </button>
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
    </div>
  );
}
