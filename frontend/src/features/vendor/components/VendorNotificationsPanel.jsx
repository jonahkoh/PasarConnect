import { useEffect } from "react";

const TYPE_LABELS = {
  claim: "Claim",
  purchase: "Purchase",
  status: "Status",
};

export default function VendorNotificationsPanel({ notifications, socket, onNotification, onClaimReceived, onPaymentArrived }) {
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
      // Also ensure the listing card shows Approve/Reject buttons.
      if (onClaimReceived && payload.claim_id) {
        onClaimReceived({ listing_id: payload.listing_id, claim_id: payload.claim_id });
      }
    }

    function handlePaymentArrived(payload) {
      onNotification((prev) => [
        {
          id: `payment-arrived-${payload.transaction_id ?? Date.now()}`,
          type: "purchase",
          title: "Buyer has arrived",
          message: `A buyer is at your location ready to collect listing #${payload.listing_id}. Please confirm or reject below.`,
          timeLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        ...prev,
      ]);
      if (onPaymentArrived) {
        onPaymentArrived({
          listing_id:     payload.listing_id,
          transaction_id: payload.transaction_id,
        });
      }
    }

    function handleClaimSuccess(payload) {
      onNotification((prev) => [
        {
          id: `claim-success-${payload.claim_id ?? Date.now()}`,
          type: "claim",
          title: "Charity claim received",
          message: `Listing #${payload.listing_id} claimed by charity #${payload.charity_id}. Waiting for charity to arrive.`,
          timeLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        ...prev,
      ]);
      // Do NOT call onClaimReceived here — Approve/Reject should only appear after charity clicks "I've Arrived".
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
          id: `payment-new-${payload.listing_id ?? Date.now()}`,
          type: "purchase",
          title: "New purchase",
          message: `Public buyer paid for listing #${payload.listing_id}. Awaiting collection.`,
          timeLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        ...prev,
      ]);
    }

    function handlePaymentCollected(payload) {
      onNotification((prev) => [
        {
          id: `payment-collected-${payload.listing_id ?? Date.now()}`,
          type: "purchase",
          title: "Collection confirmed",
          message: `Listing #${payload.listing_id} collected — payment finalised.`,
          timeLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        ...prev,
      ]);
    }

    function handlePaymentRefunded(payload) {
      onNotification((prev) => [
        {
          id: `payment-refunded-${payload.listing_id ?? Date.now()}`,
          type: "status",
          title: "Purchase refunded",
          message: `Listing #${payload.listing_id} refunded — item relisted.`,
          timeLabel: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        ...prev,
      ]);
    }

    socket.on("claim:arrived",     handleClaimArrived);
    socket.on("payment:arrived",   handlePaymentArrived);
    socket.on("claim:success",     handleClaimSuccess);
    socket.on("claim:cancelled",   handleClaimCancelled);
    socket.on("payment:success",   handlePaymentSuccess);
    socket.on("payment:collected", handlePaymentCollected);
    socket.on("payment:refunded",  handlePaymentRefunded);

    return () => {
      socket.off("claim:arrived",     handleClaimArrived);
      socket.off("payment:arrived",   handlePaymentArrived);
      socket.off("claim:success",     handleClaimSuccess);
      socket.off("claim:cancelled",   handleClaimCancelled);
      socket.off("payment:success",   handlePaymentSuccess);
      socket.off("payment:collected", handlePaymentCollected);
      socket.off("payment:refunded",  handlePaymentRefunded);
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
