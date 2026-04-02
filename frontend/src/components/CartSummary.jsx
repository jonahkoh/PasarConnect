function formatCurrency(amount) {
  return new Intl.NumberFormat("en-SG", {
    style: "currency",
    currency: "SGD",
  }).format(amount);
}

export default function CartSummary({
  items,
  totalItems,
  subtotal,
  onUpdateQuantity,
  onCheckout,
  isCheckingOut,
  footer = null,
}) {
  return (
    <aside className="cart-summary">
      <div className="cart-summary__header">
        <p className="cart-summary__eyebrow">Public Checkout</p>
        <h2>Your Cart</h2>
        <span className="cart-summary__pill">{totalItems} item(s)</span>
      </div>

      {items.length === 0 ? (
        <div className="cart-summary__empty">
          Add discounted listings to your cart and review them here before checkout.
        </div>
      ) : (
        <div className="cart-summary__list">
          {items.map((entry) => (
            <article key={entry.id} className="cart-line">
              <div className="cart-line__copy">
                <h3>{entry.name}</h3>
                <p>{entry.vendor}</p>
              </div>

              <div className="cart-line__meta">
                {onUpdateQuantity ? (
                  <div className="quantity-stepper cart-line__stepper">
                    <button
                      type="button"
                      onClick={() => onUpdateQuantity(entry.id, entry.quantity - 1)}
                      aria-label={`Decrease ${entry.name} quantity`}
                    >
                      -
                    </button>
                    <span>{entry.quantity}</span>
                    <button
                      type="button"
                      onClick={() => onUpdateQuantity(entry.id, entry.quantity + 1)}
                      disabled={entry.quantity >= entry.maxQuantity}
                      aria-label={`Increase ${entry.name} quantity`}
                    >
                      +
                    </button>
                  </div>
                ) : (
                  <span>Qty {entry.quantity}</span>
                )}
                <strong>{formatCurrency(entry.lineTotal)}</strong>
              </div>
            </article>
          ))}
        </div>
      )}

      <div className="cart-summary__totals">
        <div>
          <span>Subtotal</span>
          <strong>{formatCurrency(subtotal)}</strong>
        </div>
        <p>Pickup is coordinated directly with the vendor after payment.</p>
      </div>

      {onCheckout && (
        <button
          type="button"
          className="cart-summary__checkout"
          onClick={onCheckout}
          disabled={items.length === 0 || isCheckingOut}
        >
          {isCheckingOut ? "Processing..." : "Proceed to Checkout"}
        </button>
      )}

      {footer}
    </aside>
  );
}
