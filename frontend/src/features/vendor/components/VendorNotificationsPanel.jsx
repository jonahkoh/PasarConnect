import { useEffect } from "react";

const TYPE_LABELS = {
  claim: "Claim",
  purchase: "Purchase",
  status: "Status",
};

export default function VendorNotificationsPanel({ notifications, socket, onNotification, onClaimReceived }) {
  useEffect(() => {
    if (!socket) return;

    function handleClaimArrived(payload) {
      onNotification((prev) => [
        {
          id: `claim-arrived-${payload.claim_id ?? Date.now()}`,
          type: "claim",
          title: "Charity has arrived",
          message: `Charity #${payload.charity_id} is at your door for listing #${payload.listing_id}. Please approve or reject their collection below.`,
          timeLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        ...prev,
      ]);
    }

    function handleClaimSuccess(payload) {
      onNotification((prev) => [
        {
          id: `claim-success-${payload.claim_id ?? Date.now()}`,
          type: "claim",
          title: "Charity claim received",
          message: `Listing #${payload.listing_id} claimed by charity #${payload.charity_id}.`,
          timeLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        ...prev,
      ]);
      if (onClaimReceived && payload.claim_id) {
        onClaimReceived({ listing_id: payload.listing_id, claim_id: payload.claim_id });
      }
    }

    function handleClaimCancelled(payload) {
      onNotification((prev) => [
        {
          id: `claim-cancelled-${payload.claim_id ?? Date.now()}`,
          type: "status",
          title: "Claim cancelled",
          message: `Claim on listing #${payload.listing_id} was cancelled.`,
          timeLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        ...prev,
      ]);
    }

    function handlePaymentSuccess(payload) {
      onNotification((prev) => [
        {
          id: `payment-${payload.listing_id ?? Date.now()}`,
          type: "purchase",
          title: "Payment received",
          message: `Public purchase confirmed for listing #${payload.listing_id}.`,
          timeLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        ...prev,
      ]);
    }

    socket.on("claim:arrived",   handleClaimArrived);
    socket.on("claim:success",   handleClaimSuccess);
    socket.on("claim:cancelled", handleClaimCancelled);
    socket.on("payment:success", handlePaymentSuccess);

    return () => {
      socket.off("claim:arrived",   handleClaimArrived);
      socket.off("claim:success",   handleClaimSuccess);
      socket.off("claim:cancelled", handleClaimCancelled);
      socket.off("payment:success", handlePaymentSuccess);
    };
  }, [socket, onNotification, onClaimReceived]);

  return (
    <aside className="vendor-notifications-panel">
      <div className="vendor-panel__header">
        <div>
          <h2>Live Updates</h2>
          <p>{socket ? "Connected — receiving real-time events." : "Connect as vendor to receive live alerts."}</p>
        </div>
      </div>

      {notifications.length === 0 ? (
        <div className="empty-state">No notifications yet.</div>
      ) : (
        <div className="vendor-notifications-list">
          {notifications.map((notification) => (
            <article key={notification.id} className="vendor-notification-item">
              <span className="vendor-notification-item__type">
                {TYPE_LABELS[notification.type] ?? "Update"}
              </span>
              <h3>{notification.title}</h3>
              <p>{notification.message}</p>
              <span className="vendor-notification-item__time">
                {notification.timeLabel}
              </span>
            </article>
          ))}
        </div>
      )}
    </aside>
  );
}
