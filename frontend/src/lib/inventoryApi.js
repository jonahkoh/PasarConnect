const INVENTORY_MAP_ENDPOINT = "/api/inventory/listings/map/live";

export async function fetchLiveMapListings({ latitude, longitude, radiusKm = 5, signal } = {}) {
  const params = new URLSearchParams();

  if (typeof latitude === "number" && typeof longitude === "number") {
    params.set("latitude", String(latitude));
    params.set("longitude", String(longitude));
    params.set("radius_km", String(radiusKm));
  }

  const query = params.toString();
  const response = await fetch(
    query ? `${INVENTORY_MAP_ENDPOINT}?${query}` : INVENTORY_MAP_ENDPOINT,
    { signal }
  );

  if (!response.ok) {
    throw new Error(`Inventory map request failed (${response.status})`);
  }

  return response.json();
}
