import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import TopNav from "../components/TopNav";
import { abandonPaymentIntent, createPaymentIntent, simulateWebhookConfirmation } from "../lib/paymentApi";

function formatCurrency(amount) {
  return new Intl.NumberFormat("en-SG", {
    style: "currency",
    currency: "SGD",
  }).format(amount);
}

// Checkout steps:
//   idle          â†’ user reviewing cart
//   creating      â†’ POSTing payment intents (locking listings)
//   payment_form  â†’ mock payment form shown, waiting for user to confirm
//   processing    â†’ calling webhook to confirm each intent
//   success       â†’ all confirmed, cart cleared
//   error         â†’ one or more steps failed

export default function MarketplaceCartPage({
  cart,
  totalCartItems,
  onUpdateQuantity,
  onClearCart,
  authUser,
}) {
  const [step, setStep]                   = useState("idle");
  const [checkoutError, setCheckoutError] = useState("");
  // intents: array of { id (listing_id), name, transaction_id, client_secret, amount }
  const [intents, setIntents]             = useState([]);
  // Track which item is currently being locked so the UI can show partial progress
  const [lockingIndex, setLockingIndex]   = useState(-1);

  const subtotal = useMemo(
    () => cart.reduce((sum, entry) => sum + entry.quantity * entry.unitPrice, 0),
    [cart]
  );

  // â”€â”€ Step 1: Create a PaymentIntent for every cart item â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  // If any intent creation fails, abandon already-created intents and show error.
  async function handleCheckout() {
    setStep("creating");
    setCheckoutError("");

    const created = [];
    const userId = Number(authUser?.userId ?? 0);

    try {
      for (let i = 0; i < cart.length; i++) {
        setLockingIndex(i);
        const entry  = cart[i];
        const amount = entry.quantity * entry.unitPrice;
        const result = await createPaymentIntent(
          entry.id,
          entry.listing_version ?? 0,
          amount,
          authUser?.token,
        );
        const transactionId =
          result.payment_intent_id ??
          result.client_secret?.split("_secret_")[0] ??
          result.client_secret;
        created.push({
          id:             entry.id,
          name:           entry.name,
          transaction_id: transactionId,
          client_secret:  result.client_secret,
          amount,
        });
      }
      setLockingIndex(-1);
      setIntents(created);
      setStep("payment_form");
    } catch (err) {
      setLockingIndex(-1);
      // Roll back any intents we already created before the failure
      for (const intent of created) {
        await abandonPaymentIntent(intent.transaction_id, userId, authUser?.token);
      }
      setIntents([]);
      setCheckoutError(err.message || "Could not reserve your items. Please try again.");
      setStep("error");
    }
  }

  // â”€â”€ Step 2: Simulate Stripe webhook confirmation for every intent â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  async function handleConfirmPayment() {
    setStep("processing");
    setCheckoutError("");

    try {
      for (const intent of intents) {
        await simulateWebhookConfirmation(intent.transaction_id, intent.amount);
      }
      onClearCart();
      setIntents([]);
      setStep("success");
    } catch (err) {
      // Partial failure â€” at least one webhook call failed.  Leave intents in
      // state so the user can see what happened; they'll need to contact support
      // for partial completions, but for demo mode this is a clean error screen.
      setCheckoutError(err.message || "Payment confirmation failed. Please contact support.");
      setStep("error");
    }
  }

  // â”€â”€ Cancel from payment form â€” abandon all pending intents â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  async function handleAbandonCheckout() {
    const userId = Number(authUser?.userId ?? 0);
    setStep("creating"); // Reuse "creating" overlay during abandon
    for (const intent of intents) {
      await abandonPaymentIntent(intent.transaction_id, userId, authUser?.token);
    }
    setIntents([]);
    setStep("idle");
  }

  function handleRetry() {
    setIntents([]);
    setStep("idle");
    setCheckoutError("");
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

        {/* â”€â”€ Success screen â”€â”€ */}
        {step === "success" && (
          <div className="alert-success">
            <strong>Payment confirmed!</strong> Your items are reserved â€” check with each
            vendor for pickup timing. A confirmation has been sent to your account.
            <div style={{ marginTop: "10px" }}>
              <Link to="/marketplace/orders" className="link-button">View my orders</Link>
              {" · "}
              <Link to="/marketplace">Browse more items</Link>
              {" · "}
              <Link to="/">Home</Link>
            </div>
          </div>
        )}

        {/* â”€â”€ Error screen â”€â”€ */}
        {step === "error" && (
          <div className="alert-error">
            <strong>Something went wrong:</strong> {checkoutError}
            <div style={{ marginTop: "10px" }}>
              <button type="button" className="link-button" onClick={handleRetry}>
                Return to cart
              </button>
              {" Â· "}
              <Link to="/marketplace">Browse marketplace</Link>
            </div>
          </div>
        )}

        {/* â”€â”€ Abandoning checkout overlay â”€â”€ */}
        {step === "creating" && intents.length > 0 && (
          <div className="payment-form payment-form--processing">
            <p>Releasing reserved itemsâ€¦</p>
          </div>
        )}

        {/* â”€â”€ Locking items overlay (no intents yet = still creating) â”€â”€ */}
        {step === "creating" && intents.length === 0 && (
          <div className="payment-form payment-form--processing">
            {lockingIndex >= 0 ? (
              <p>Reserving <strong>{cart[lockingIndex]?.name}</strong> ({lockingIndex + 1}/{cart.length})â€¦</p>
            ) : (
              <p>Preparing checkoutâ€¦</p>
            )}
            <p className="payment-form__note" style={{ marginTop: "8px" }}>
              You can safely close this tab â€” no charge has been made yet.
            </p>
          </div>
        )}

        {/* â”€â”€ Processing overlay â”€â”€ */}
        {step === "processing" && (
          <div className="payment-form payment-form--processing">
            <p>Confirming your paymentâ€¦</p>
            <p className="payment-form__note" style={{ marginTop: "8px" }}>
              Please do not close this tab.
            </p>
          </div>
        )}

        {/* â”€â”€ Payment confirmation form (mock Stripe UI) â”€â”€ */}
        {step === "payment_form" && (
          <div className="payment-form">
            <h2>Confirm Payment</h2>
            <p className="payment-form__note">
              Demo mode â€” no real card is charged. Click <strong>Pay</strong> to simulate
              Stripe confirmation.
            </p>

            <div className="payment-form__items">
              {intents.map((intent) => (
                <div key={intent.id} className="payment-form__line">
                  <span>{intent.name}</span>
                  <strong>{formatCurrency(intent.amount)}</strong>
                </div>
              ))}
              <div className="payment-form__line payment-form__line--total">
                <span>Total</span>
                <strong>{formatCurrency(subtotal)}</strong>
              </div>
            </div>

            <div className="payment-form__mock-card">
              <label>Card number</label>
              <input
                className="payment-form__input"
                type="text"
                defaultValue="4242 4242 4242 4242"
                readOnly
                aria-label="Mock card number"
              />
              <div className="payment-form__card-row">
                <div>
                  <label>Expiry</label>
                  <input
                    className="payment-form__input"
                    type="text"
                    defaultValue="12/28"
                    readOnly
                    aria-label="Mock expiry"
                  />
                </div>
                <div>
                  <label>CVV</label>
                  <input
                    className="payment-form__input"
                    type="text"
                    defaultValue="123"
                    readOnly
                    aria-label="Mock CVV"
                  />
                </div>
              </div>
            </div>

            <button
              type="button"
              className="cart-summary__checkout"
              onClick={handleConfirmPayment}
            >
              Pay {formatCurrency(subtotal)}
            </button>
            <button
              type="button"
              className="link-button"
              style={{ marginTop: "12px", display: "block", textAlign: "center", width: "100%" }}
              onClick={handleAbandonCheckout}
            >
              Cancel â€” release reserved items and return to cart
            </button>
          </div>
        )}

        {/* â”€â”€ Cart view (idle only â€” creating/processing have overlays) â”€â”€ */}
        {step === "idle" && (
          <>
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

                        <strong className="cart-item__price">
                          {formatCurrency(entry.unitPrice)}
                        </strong>
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
                    disabled={!authUser?.token}
                  >
                    Checkout
                  </button>

                  {!authUser?.token && (
                    <p className="cart-page__login-hint">
                      <Link to="/login">Log in</Link> to complete your purchase.
                    </p>
                  )}
                </aside>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
