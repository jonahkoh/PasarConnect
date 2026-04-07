function formatSummary(summary) {
  if (!summary) {
    return "";
  }

  const parts = [];

  if (summary.success > 0) {
    parts.push(`${summary.success} claims confirmed`);
  }
  if (summary.conflict > 0) {
    parts.push(`${summary.conflict} already claimed`);
  }
  if (summary.eligibility > 0) {
    parts.push(`${summary.eligibility} eligibility failure`);
  }
  if (summary.unavailable > 0) {
    parts.push(`${summary.unavailable} no longer available`);
  }
  if (summary.queue_window > 0) {
    parts.push(`${summary.queue_window} in queue window (join below)`);
  }

  return parts.join(", ");
}

export default function ClaimSummaryCard({
  activeView,
  selectedItems,
  claimHistory,
  submissionSummary,
  isSubmitting,
  onChangeView,
  onRemoveItem,
  onSubmitClaims,
}) {
  return (
    <aside className="cart-summary claim-summary">
      <div className="cart-summary__header">
        <p className="cart-summary__eyebrow">Charity Claim</p>
        <h2>Claim Queue</h2>
        <span className="cart-summary__pill">
          {selectedItems.length} item(s) selected
        </span>
      </div>

      <p className="claim-queue__helper">
        Items are only confirmed after submission and may become unavailable in
        real time.
      </p>

      {submissionSummary && (
        <div className="claim-queue__summary">{formatSummary(submissionSummary)}</div>
      )}

      <div className="claim-queue__tabs">
        <button
          type="button"
          className={`claim-queue__tab ${
            activeView === "queue" ? "claim-queue__tab--active" : ""
          }`}
          onClick={() => onChangeView("queue")}
        >
          Claim Queue
        </button>

        <button
          type="button"
          className={`claim-queue__tab ${
            activeView === "history" ? "claim-queue__tab--active" : ""
          }`}
          onClick={() => onChangeView("history")}
        >
          Claim History
        </button>
      </div>

      {activeView === "queue" ? (
        <>
          {selectedItems.length === 0 ? (
            <div className="cart-summary__empty">
              Select charity-eligible items from the browse grid to build a claim
              queue.
            </div>
          ) : (
            <div className="cart-summary__list">
              {selectedItems.map((item) => (
                <article key={item.id} className="cart-line">
                  <div>
                    <h3>{item.name}</h3>
                    <p>{item.vendor}</p>
                    <p className="claim-queue__meta">{item.pickupWindow}</p>
                  </div>

                  <button
                    type="button"
                    className="claim-queue__remove"
                    onClick={() => onRemoveItem(item.id)}
                  >
                    Remove
                  </button>
                </article>
              ))}
            </div>
          )}

          <button
            type="button"
            className="cart-summary__checkout"
            onClick={onSubmitClaims}
            disabled={selectedItems.length === 0 || isSubmitting}
          >
            {isSubmitting ? "Submitting..." : "Submit Selected Claims"}
          </button>
        </>
      ) : (
        <>
          {claimHistory.length === 0 ? (
            <div className="cart-summary__empty">
              Successful claims will appear here with pending collection status.
        
            </div>
          ) : (
            <div className="cart-summary__list">
              {claimHistory.map((item) => (
                <article key={item.historyId} className="cart-line">
                  <div>
                    <h3>{item.name}</h3>
                    <p>{item.vendor}</p>
                    <p className="claim-queue__meta">{item.claimedAtLabel}</p>
                  </div>

                  <span className="claim-history__status">{item.status}</span>
                </article>
              ))}
            </div>
          )}
        </>
      )}
    </aside>
  );
}
