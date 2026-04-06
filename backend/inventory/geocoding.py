import logging
import httpx

logger = logging.getLogger(__name__)

ONEMAP_SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"
_TIMEOUT_SECONDS = 5.0


class GeocodingError(Exception):
    """Raised when an address cannot be geocoded."""


async def geocode_address(address: str) -> tuple[float, float]:
    """
    Convert a Singapore address string to (latitude, longitude) using OneMap API.

    Raises:
        GeocodingError — if no results found, request times out, or HTTP error.
    """
    params = {
        "searchVal": address,
        "returnGeom": "Y",
        "getAddrDetails": "Y",
        "pageNum": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(ONEMAP_SEARCH_URL, params=params)
        response.raise_for_status()

        results = response.json().get("results", [])
        if not results:
            raise GeocodingError(f"No location found for address: {address!r}")

        first = results[0]
        lat = float(first["LATITUDE"])
        lng = float(first["LONGITUDE"])
        logger.info("Geocoded %r -> (%.6f, %.6f)", address, lat, lng)
        return lat, lng

    except httpx.TimeoutException:
        raise GeocodingError(f"OneMap request timed out for address: {address!r}")
    except httpx.HTTPError as e:
        raise GeocodingError(f"OneMap HTTP error: {e}")
