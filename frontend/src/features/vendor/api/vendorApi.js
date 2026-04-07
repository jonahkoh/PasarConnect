const INVENTORY_BASE = "/api/inventory";
const CLAIMS_BASE = "/api/claims";

function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Normalise an inventory API listing into the shape VendorListingCard expects.
 * API: { id, vendor_id, title, quantity, weight_kg, expiry, image_url, status, version, ... }
 * UI: { id, name, quantity, status, expiryLabel, pickupWindow, imageUrl, lastUpdatedLabel, version }
 */
function normalizeVendorListing(raw) {
  const expiry = new Date(raw.expiry);
  const expiryMs = expiry.getTime() - Date.now();
  const expiryMins = Math.round(expiryMs / 60000);
  const expiryLabel =
    expiryMs <= 0
      ? "Expired"
      : expiryMins < 60
        ? `Expires in ${expiryMins}m`
        : `Expires ${expiry.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;

  const quantityLabel =
    raw.quantity != null
      ? raw.quantity
      : raw.weight_kg != null
        ? `${raw.weight_kg} kg`
        : "—";

  return {
    id: raw.id,
    name: raw.title,
    quantity: quantityLabel,
    status: raw.status,
    expiryLabel,
    pickupWindow: "Check listing",
    imageUrl: raw.image_url?.startsWith("http") ? raw.image_url : null,
    lastUpdatedLabel: raw.updated_at
      ? `Updated ${new Date(raw.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
      : "",
    version: raw.version,
    vendor_id: String(raw.vendor_id),
  };
}

/**
 * Fetch all listings from inventory, filter client-side to those owned by this vendor.
 * Returns the array in normalised UI shape.
 */
export async function fetchVendorListings(token, vendorId) {
  const res = await fetch(INVENTORY_BASE, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Inventory fetch failed (${res.status})`);
  const data = await res.json();
  const id = String(vendorId);
  return data
    .filter((item) => String(item.vendor_id) === id)
    .map(normalizeVendorListing);
}

/**
 * POST /api/claims/{claim_id}/approve
 */
export async function approveClaim(claimId, token) {
  const res = await fetch(`${CLAIMS_BASE}/${claimId}/approve`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(
      (typeof data?.detail === "string" ? data.detail : null) ??
        `Approve failed (${res.status})`
    );
  }
  return res.json();
}

/**
 * POST /api/claims/{claim_id}/reject
 */
export async function rejectClaim(claimId, token) {
  const res = await fetch(`${CLAIMS_BASE}/${claimId}/reject`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(
      (typeof data?.detail === "string" ? data.detail : null) ??
        `Reject failed (${res.status})`
    );
  }
  return res.json();
}

const PAYMENTS_BASE = "/api/payments";

/**
 * POST /api/payments/{transaction_id}/approve
 * Vendor confirms the buyer has collected the item.
 */
export async function approvePayment(transactionId, token) {
  const res = await fetch(`${PAYMENTS_BASE}/${transactionId}/approve`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(
      (typeof data?.detail === "string" ? data.detail : null) ??
        `Approve payment failed (${res.status})`
    );
  }
  return res.json();
}

/**
 * POST /api/payments/{transaction_id}/reject
 * Vendor rejects the collection — buyer is refunded.
 */
export async function rejectPayment(transactionId, token) {
  const res = await fetch(`${PAYMENTS_BASE}/${transactionId}/reject`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(
      (typeof data?.detail === "string" ? data.detail : null) ??
        `Reject payment failed (${res.status})`
    );
  }
  return res.json();
}
