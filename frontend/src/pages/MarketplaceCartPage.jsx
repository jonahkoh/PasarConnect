import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { loadStripe } from "@stripe/stripe-js";
import { Elements, CardElement, useStripe, useElements } from "@stripe/react-stripe-js";
import TopNav from "../components/TopNav";
import Toast from "../components/Toast";
import { abandonPaymentIntent, createPaymentIntent, simulateWebhookConfirmation } from "../lib/paymentApi";

const stripePromise = loadStripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY);

function formatCurrency(amount) {
  return new Intl.NumberFormat("en-SG", {
    style: "currency",
    currency: "SGD",
  }).format(amount);
}

/**
 * Inner form component — must live inside an <Elements> provider to use
 * useStripe / useElements hooks.
 */
function StripeCheckoutForm({ intents, subtotal, onSuccess, onError, onCancel }) {
  const stripe   = useStripe();
  const elements = useElements();
  const [cardError,   setCardError]   = useState("");
  const [processing, setProcessing] = useState(false);

  async function handlePay(e) {
    e.preventDefault();
    if (!stripe || !elements) return;
    setProcessing(true);
    setCardError("");

    const cardElement = elements.getElement(CardElement);
    let paymentMethodId = null;

    try {
      for (const intent of intents) {
        // Reuse the PaymentMethod created on the first confirmation
        const params = paymentMethodId
          ? { payment_method: paymentMethodId }
          : { payment_method: { card: cardElement } };

        const { paymentIntent, error } = await stripe.confirmCardPayment(
          intent.client_secret,
          params,
        );
        if (error) throw new Error(error.message);
        if (!paymentMethodId && paymentIntent) {
          paymentMethodId = paymentIntent.payment_method;
        }
        // Advance backend PENDING → SUCCESS and inventory PENDING_PAYMENT → SOLD_PENDING_COLLECTION
        await simulateWebhookConfirmation(intent.transaction_id, intent.amount);
      }
      onSuccess();
    } catch (err) {
      onError(err.message);
    }
  }

  return (
    <form onSubmit={handlePay} className="payment-form">
      <h2>Confirm Payment</h2>

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

      <div className="payment-form__card-element">
        <CardElement options={{ style: { base: { fontSize: "16px", color: "#1a1a1a" } } }} />
      </div>

      {cardError && (
        <p className="payment-form__error" role="alert">{cardError}</p>
      )}

      <button
        type="submit"
        className="cart-summary__checkout"
        disabled={!stripe || processing}
      >
        {processing ? "Processing…" : `Pay ${formatCurrency(subtotal)}`}
      </button>
      <button
        type="button"
        className="link-button"
        style={{ marginTop: "12px", display: "block", textAlign: "center", width: "100%" }}
        onClick={onCancel}
        disabled={processing}
      >
        Cancel – release reserved items and return to cart
      </button>
    </form>
  );
}

// Checkout steps:
//   idle          → user reviewing cart
//   creating      → POSTing payment intents (locking listings)
//   payment_form  → Stripe Elements form shown, waiting for card confirmation
//   success       → Stripe confirmed payment, cart cleared
//   error         → one or more steps failed

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
  const [toast, setToast]                 = useState(null);

  function showToast(msg) {
    setToast(msg);
    setTimeout(() => setToast(null), 6000);
  }

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
      <Toast message={toast} onDismiss={() => setToast(null)} />

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

        {/* Payment form — Stripe Elements */}
        {step === "payment_form" && (
          <Elements stripe={stripePromise}>
            <StripeCheckoutForm
              intents={intents}
              subtotal={subtotal}
              onSuccess={() => { onClearCart(); setIntents([]); setStep("success"); }}
              onError={(msg) => { showToast(msg); setIntents([]); setStep("idle"); }}
              onCancel={handleAbandonCheckout}
            />
          </Elements>
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
