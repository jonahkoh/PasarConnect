const API_BASE = "/api/inventory";

/**
 * Maps the inventory API response shape to the UI shape expected by listing components.
 *
 * API:  { id, vendor_id, title, description, quantity, weight_kg, expiry, image_url,
 *         status, version, latitude, longitude, geohash, created_at, updated_at }
 * UI:   { id, name, vendor, address, latitude, longitude, imageUrl, distanceKm,
 *         quantityLabel, priceLabel, badge, charityWindow, status, version,
 *         category, pickupWindow }
 */
function normalizeApiListing(raw) {
  const quantity =
    raw.quantity != null
      ? `${raw.quantity} unit${raw.quantity !== 1 ? "s" : ""}`
      : raw.weight_kg != null
        ? `${raw.weight_kg} kg`
        : "\u2014";

  const expiryMs   = new Date(raw.expiry).getTime() - Date.now();
  const expiryMins = Math.max(0, Math.round(expiryMs / 60000));
  const charityWindow =
    expiryMs > 0
      ? expiryMins >= 60
        ? `${Math.round(expiryMins / 60)}h remaining`
        : `${expiryMins}m remaining`
      : "";

  return {
    id:            raw.id,
    name:          raw.title,
    vendor:        raw.vendor_id,
    address:       raw.description ?? "",
    latitude:      raw.latitude  ?? null,
    longitude:     raw.longitude ?? null,
    imageUrl:      raw.image_url ?? null,
    distanceKm:    null,
    quantityLabel: quantity,
    priceLabel:    "Free",
    badge:         raw.status === "AVAILABLE" ? "Available" : raw.status,
    charityWindow,
    status:        raw.status,
    version:       raw.version,
    category:      "Food",
    pickupWindow:  "Check listing",
  };
}

function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// GET /api/inventory — all listings (requires JWT via Kong)
export async function fetchListings(token, { signal } = {}) {
  const response = await fetch(API_BASE, {
    headers: authHeaders(token),
    signal,
  });
  if (!response.ok) {
    throw new Error(`Inventory fetch failed (${response.status})`);
  }
  const data = await response.json();
  return data.map(normalizeApiListing);
}

// GET /api/inventory/search/nearby — geohash proximity search (requires JWT)
export async function fetchNearbyListings({ lat, lng, radius = 5, token, signal } = {}) {
  const params = new URLSearchParams({
    latitude:  String(lat),
    longitude: String(lng),
    radius_km: String(radius),
  });
  const response = await fetch(`${API_BASE}/search/nearby?${params}`, {
    headers: authHeaders(token),
    signal,
  });
  if (!response.ok) {
    throw new Error(`Nearby listings fetch failed (${response.status})`);
  }
  const data = await response.json();
  return data.map(normalizeApiListing);
}

// GET /api/inventory/map/live — AVAILABLE listings with coordinates (requires JWT)
// Kong strips /api/inventory → upstream receives /listings/map/live ✓
// (The old path /api/inventory/listings/map/live only worked with the direct Vite
//  proxy rewrite; through Kong it produced a double /listings prefix.)
export async function fetchLiveMapListings({ latitude, longitude, radiusKm = 5, token, signal } = {}) {
  const params = new URLSearchParams();
  if (typeof latitude === "number" && typeof longitude === "number") {
    params.set("latitude",  String(latitude));
    params.set("longitude", String(longitude));
    params.set("radius_km", String(radiusKm));
  }
  const query = params.toString();
  const response = await fetch(
    `${API_BASE}/map/live${query ? `?${query}` : ""}`,
    { headers: authHeaders(token), signal },
  );
  if (!response.ok) {
    throw new Error(`Inventory map request failed (${response.status})`);
  }
  const data = await response.json();
  return data.map(normalizeApiListing);
}
