/**
 * OneMap API client — Singapore geocoding and place search.
 *
 * The search endpoint is public / unauthenticated and supports CORS from browsers.
 * If OneMap ever requires authentication or restricts CORS, replace the fetch URL
 * with "/api/geocode/search" (backend proxy) — no other change needed.
 */

const ONEMAP_SEARCH_URL =
  "https://www.onemap.gov.sg/api/common/elastic/search";

/**
 * Search for Singapore addresses / place names.
 *
 * @param {string} query
 * @param {{ signal?: AbortSignal }} [opts]
 * @returns {Promise<Array<{ label: string, building: string|null, postal: string|null, lat: number, lng: number }>>}
 */
export async function searchOneMapPlaces(query, { signal } = {}) {
  if (!query?.trim()) return [];

  const params = new URLSearchParams({
    searchVal:      query.trim(),
    returnGeom:     "Y",
    getAddrDetails: "Y",
    pageNum:        1,
  });

  const res = await fetch(`${ONEMAP_SEARCH_URL}?${params}`, { signal });
  if (!res.ok) throw new Error(`OneMap search failed (${res.status})`);

  const data = await res.json();
  return (data.results || []).slice(0, 8).map((r) => ({
    label:    r.ADDRESS  || r.SEARCHVAL,
    building: r.BUILDING && r.BUILDING !== "NIL" ? r.BUILDING : null,
    postal:   r.POSTAL   && r.POSTAL   !== "NIL" ? r.POSTAL   : null,
    lat:      parseFloat(r.LATITUDE),
    lng:      parseFloat(r.LONGITUDE),
  }));
}
