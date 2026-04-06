const LISTINGS_BASE = "/api/listings";

function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * POST /api/listings
 *
 * Kong route: strip_path=false → listing-service receives /api/listings
 * vendor_id is extracted server-side from the JWT — never sent in the body.
 *
 * Payload fields (all optional except title, expiry, image_url, and one of quantity/weight_kg):
 *   title, description, quantity, weight_kg, expiry (ISO string), image_url,
 *   latitude, longitude
 *
 * Returns { listing_id, listed_at }
 */
export async function createListing(payload, token) {
  const res = await fetch(LISTINGS_BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((e) => e.msg ?? e).join("; ")
          : `Create listing failed (${res.status})`;
    throw new Error(msg);
  }
  return data; // { listing_id, listed_at }
}
