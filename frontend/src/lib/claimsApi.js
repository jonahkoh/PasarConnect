const CLAIMS_BASE = "/api/claims";

function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function extractDetail(data) {
  if (!data?.detail) return null;
  return typeof data.detail === "object" ? data.detail : null;
}

function extractMessage(data, fallback) {
  const detail = data?.detail;
  if (!detail) return fallback;
  if (typeof detail === "object") return detail.message ?? fallback;
  return String(detail);
}

/**
 * POST /api/claims
 * Body: { listing_id, charity_id, listing_version }
 *
 * Throws an error with `.status` and `.detail` on non-2xx.
 * 409 detail.error values: "queue_window_active" | "queue_exists"
 */
export async function submitClaim({ listing_id, charity_id, listing_version, token }) {
  const res = await fetch(CLAIMS_BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ listing_id, charity_id, listing_version }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(extractMessage(data, `Claim failed (${res.status})`));
    err.status = res.status;
    err.detail = extractDetail(data);
    throw err;
  }
  return data;
}

/**
 * POST /api/claims/{listing_id}/waitlist
 * Body: { charity_id }
 *
 * Returns: { listing_id, charity_id, position }
 */
export async function joinWaitlist({ listing_id, charity_id, token }) {
  const res = await fetch(`${CLAIMS_BASE}/${listing_id}/waitlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ charity_id }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(extractMessage(data, `Join waitlist failed (${res.status})`));
    err.status = res.status;
    err.detail = extractDetail(data);
    throw err;
  }
  return data;
}

/**
 * GET /api/claims/{listing_id}/waitlist
 * Returns the caller's waitlist entry, or null if not found.
 */
export async function getWaitlistPosition({ listing_id, charity_id, token }) {
  const res = await fetch(`${CLAIMS_BASE}/${listing_id}/waitlist`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(`Get waitlist failed (${res.status})`);
  const entries = await res.json();
  return entries.find((e) => e.charity_id === charity_id) ?? null;
}

/**
 * POST /api/claims/{claim_id}/arrive
 * Signals that the charity has arrived on-site for collection.
 */
export async function postArrive(claim_id, token) {
  const res = await fetch(`${CLAIMS_BASE}/${claim_id}/arrive`, {
    method: "POST",
    headers: authHeaders(token),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(extractMessage(data, `Arrive notification failed (${res.status})`));
  }
  return data;
}

/**
 * GET /api/claims/mine
 * Returns all claims for the authenticated charity (from JWT sub).
 * Shape: [{ id, listing_id, charity_id, listing_version, status, created_at, updated_at }]
 */
export async function fetchMyClaims(token) {
  const res = await fetch(`${CLAIMS_BASE}/mine`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Fetch my claims failed (${res.status})`);
  return res.json();
}

/**
 * GET /api/claims/listing/{listing_id}/active
 * Returns the current pending claim for a listing (for vendor use).
 * Shape: { id, listing_id, charity_id, status, ... }
 */
export async function fetchActiveClaimForListing(listing_id, token) {
  const res = await fetch(`${CLAIMS_BASE}/listing/${listing_id}/active`, {
    headers: authHeaders(token),
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Fetch active claim failed (${res.status})`);
  return res.json();
}

/**
 * POST /api/claims/{listing_id}/waitlist/accept
 * Charity accepts an OFFERED waitlist slot.
 * Body: { charity_id }
 * Returns: claim record { id, listing_id, charity_id, status, ... }
 */
export async function acceptWaitlistOffer({ listing_id, charity_id, token }) {
  const res = await fetch(`${CLAIMS_BASE}/${listing_id}/waitlist/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ charity_id }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(extractMessage(data, `Accept offer failed (${res.status})`));
    err.status = res.status;
    err.detail = extractDetail(data);
    throw err;
  }
  return data;
}

/**
 * POST /api/claims/{listing_id}/waitlist/decline
 * Charity declines an OFFERED waitlist slot.
 * Body: { charity_id }
 */
export async function declineWaitlistOffer({ listing_id, charity_id, token }) {
  const res = await fetch(`${CLAIMS_BASE}/${listing_id}/waitlist/decline`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ charity_id }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(extractMessage(data, `Decline offer failed (${res.status})`));
    err.status = res.status;
    err.detail = extractDetail(data);
    throw err;
  }
  return data;
}

/**
 * DELETE /api/claims/{claim_id}
 * Charity cancels an active PENDING_COLLECTION claim.
 * Body: { charity_id }
 * Returns: { status: "cancelled", late_cancel_warning: boolean }
 * late_cancel_warning is true when cancelled after the 1-minute grace window.
 */
export async function cancelClaim({ claim_id, charity_id, token }) {
  const res = await fetch(`${CLAIMS_BASE}/${claim_id}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ charity_id }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(extractMessage(data, `Cancel claim failed (${res.status})`));
    err.status = res.status;
    err.detail = extractDetail(data);
    throw err;
  }
  return data;
}
