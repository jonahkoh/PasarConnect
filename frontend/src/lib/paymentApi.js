/**
 * Payment Service helpers — wraps the payment orchestrator API.
 *
 * All calls go through Kong (/api/payments) and require a valid JWT.
 * The webhook call (/webhooks/stripe) is Kong-unprotected, mirroring
 * production where Stripe calls it directly.  In mock mode the frontend
 * plays the role of Stripe by calling it after a user confirms payment.
 */

const PAYMENT_BASE = "/api/payments";
const WEBHOOK_URL  = "/webhooks/stripe";

function authHeaders(token) {
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

/**
 * Workflow 1 — Create a PaymentIntent for a single cart item.
 *
 * Locks the listing in Inventory (AVAILABLE → PENDING_PAYMENT) and
 * creates a PENDING record in the Payment Log.
 *
 * @param {number} listingId
 * @param {number} listingVersion - current inventory version (optimistic lock)
 * @param {string} token          - RS256 JWT from sessionStorage
 * @returns {{ client_secret: string }} — mock client_secret for demo use
 */
export async function createPaymentIntent(listingId, listingVersion, token) {
  const response = await fetch(`${PAYMENT_BASE}/intent`, {
    method:  "POST",
    headers: authHeaders(token),
    body:    JSON.stringify({
      listing_id:      listingId,
      listing_version: listingVersion,
    }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message =
      (typeof body.detail === "string" ? body.detail : body.detail?.message) ||
      `Payment intent failed (${response.status})`;
    throw Object.assign(new Error(message), { status: response.status, body });
  }

  return response.json(); // { client_secret }
}

/**
 * Workflow 2 (Mock) — Simulate Stripe webhook confirmation.
 *
 * In production Stripe fires this automatically after the buyer confirms.
 * In mock mode the frontend calls it directly once the user clicks "Pay".
 *
 * Moves the listing PENDING_PAYMENT → SOLD_PENDING_COLLECTION and sets
 * the Payment Log to SUCCESS.  Also publishes payment.success via RabbitMQ.
 *
 * @param {string} transactionId - the payment_intent_id returned by createPaymentIntent
 * @param {number} amount        - must match the amount used at intent creation
 */
export async function simulateWebhookConfirmation(transactionId, amount) {
  const response = await fetch(WEBHOOK_URL, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({
      stripe_transaction_id: transactionId,
      amount,
    }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message =
      (typeof body.detail === "string" ? body.detail : body.detail?.message) ||
      `Webhook confirmation failed (${response.status})`;
    throw Object.assign(new Error(message), { status: response.status, body });
  }

  return response.json(); // { status: "ok", transaction_id }
}

/**
 * Cancel a payment within the cancellation window.
 *
 * @param {string} transactionId
 * @param {number} userId
 * @param {string} token
 */
export async function cancelPayment(transactionId, userId, token) {
  const response = await fetch(`${PAYMENT_BASE}/${transactionId}/cancel`, {
    method:  "POST",
    headers: authHeaders(token),
    body:    JSON.stringify({ user_id: userId }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message =
      (typeof body.detail === "string" ? body.detail : body.detail?.message) ||
      `Cancel failed (${response.status})`;
    throw Object.assign(new Error(message), { status: response.status, body });
  }

  return response.json();
}

/**
 * Abandon a PENDING payment intent before Stripe confirmation.
 *
 * Called when the user exits the payment form without paying.
 * Rolls the inventory listing back to AVAILABLE and marks the log as REFUNDED.
 *
 * @param {string} transactionId
 * @param {number} userId
 * @param {string} token
 */
export async function abandonPaymentIntent(transactionId, userId, token) {
  const response = await fetch(`${PAYMENT_BASE}/${transactionId}/intent`, {
    method:  "DELETE",
    headers: authHeaders(token),
    body:    JSON.stringify({ user_id: userId }),
  });

  if (!response.ok) {
    // Non-fatal: log the error but don't surface it to the user — the intent
    // may already have timed out or been processed.  The caller decides.
    const body = await response.json().catch(() => ({}));
    console.warn("[paymentApi] abandonPaymentIntent failed for", transactionId, body);
    return null;
  }

  return response.json();
}

/**
 * Fetch the authenticated user's purchase history.
 *
 * @param {string} token - RS256 JWT from sessionStorage
 * @returns {Array<{transaction_id, listing_id, amount, status, created_at, updated_at}>}
 */
export async function fetchPurchaseHistory(token) {
  const response = await fetch(`${PAYMENT_BASE}/history`, {
    headers: authHeaders(token),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message =
      (typeof body.detail === "string" ? body.detail : body.detail?.message) ||
      `History fetch failed (${response.status})`;
    throw Object.assign(new Error(message), { status: response.status });
  }

  return response.json();
}

/**
 * Signal that the buyer has arrived on-site for item collection.
 * Notifies the vendor via Socket.io (payment.arrived → listing room).
 *
 * @param {string} transactionId
 * @param {string} token
 */
export async function reportArrived(transactionId, token) {
  const response = await fetch(`${PAYMENT_BASE}/${transactionId}/arrived`, {
    method:  "POST",
    headers: authHeaders(token),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message =
      (typeof body.detail === "string" ? body.detail : body.detail?.message) ||
      `Arrival signal failed (${response.status})`;
    throw Object.assign(new Error(message), { status: response.status, body });
  }

  return response.json();
}
