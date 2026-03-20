import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import TopNav from "../components/TopNav";

function formatCurrency(amount) {
  return new Intl.NumberFormat("en-SG", {
    style: "currency",
    currency: "SGD",
  }).format(amount);
}

export default function MarketplaceCartPage({
  cart,
  totalCartItems,
  onUpdateQuantity,
  onClearCart,
}) {
  const [message, setMessage] = useState("");
  const [isCheckingOut, setIsCheckingOut] = useState(false);

  const subtotal = useMemo(
    () => cart.reduce((sum, entry) => sum + entry.quantity * entry.unitPrice, 0),
    [cart]
  );

  async function handleCheckout() {
    setIsCheckingOut(true);
    setMessage("");

    await new Promise((resolve) => setTimeout(resolve, 500));

    onClearCart();
    setIsCheckingOut(false);
    setMessage("Checkout complete. The vendor pickup instructions are ready.");
  }

  return (
    <div className="app-shell">
      <TopNav cartCount={totalCartItems} />

      <main className="page">
        <section className="cart-page__hero">
          <p className="cart-page__eyebrow">Marketplace Cart</p>
          <h1>Review your order</h1>
          <p>
            Adjust quantities, confirm your subtotal, and proceed to the pickup
            handoff.
          </p>
        </section>

        {message && <div className="alert-success">{message}</div>}

        {cart.length === 0 ? (
          <div className="empty-state">
            Your cart is empty. <Link to="/marketplace">Browse marketplace items</Link>.
          </div>
        ) : (
          <section className="cart-page">
            <div className="cart-page__list">
              {cart.map((entry) => (
                <article key={entry.id} className="cart-item">
                  <img
                    className="cart-item__image"
                    src={entry.imageUrl}
                    alt={entry.name}
                  />

                  <div className="cart-item__content">
                    <div>
                      <h2>{entry.name}</h2>
                      <p>{entry.vendor}</p>
                    </div>

                    <div className="cart-item__controls">
                      <div className="quantity-stepper">
                        <button
                          type="button"
                          onClick={() => onUpdateQuantity(entry.id, entry.quantity - 1)}
                        >
                          -
                        </button>
                        <span>{entry.quantity}</span>
                        <button
                          type="button"
                          onClick={() => onUpdateQuantity(entry.id, entry.quantity + 1)}
                        >
                          +
                        </button>
                      </div>

                      <strong>
                        {formatCurrency(entry.quantity * entry.unitPrice)}
                      </strong>
                    </div>
                  </div>
                </article>
              ))}
            </div>

            <aside className="cart-checkout">
              <h2>Order Summary</h2>
              <div className="cart-checkout__row">
                <span>Items</span>
                <strong>{totalCartItems}</strong>
              </div>
              <div className="cart-checkout__row">
                <span>Subtotal</span>
                <strong>{formatCurrency(subtotal)}</strong>
              </div>
              <p>
                Pickup timing is coordinated directly with the vendor after payment.
              </p>

              <button
                type="button"
                className="cart-summary__checkout"
                onClick={handleCheckout}
                disabled={isCheckingOut}
              >
                {isCheckingOut ? "Processing..." : "Checkout"}
              </button>
            </aside>
          </section>
        )}
      </main>
    </div>
  );
}
