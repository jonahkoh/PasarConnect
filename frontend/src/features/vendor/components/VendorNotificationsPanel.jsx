const TYPE_LABELS = {
  claim: "Claim",
  purchase: "Purchase",
  status: "Status",
};

export default function VendorNotificationsPanel({ notifications }) {
  return (
    <aside className="vendor-notifications-panel">
      <div className="vendor-panel__header">
        <div>
          <h2>Live Updates</h2>
          <p>WebSocket events can plug into this panel next.</p>
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
