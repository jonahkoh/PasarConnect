import { useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import L, { latLngBounds } from "leaflet";
import "leaflet/dist/leaflet.css";

const USER_PIN_ICON = L.divIcon({
  html: `<svg width="24" height="32" viewBox="0 0 24 32" xmlns="http://www.w3.org/2000/svg">
    <path d="M12 0C5.373 0 0 5.373 0 12c0 9 12 20 12 20s12-11 12-20C24 5.373 18.627 0 12 0z" fill="#e63946" stroke="white" stroke-width="2"/>
    <circle cx="12" cy="12" r="5" fill="white"/>
  </svg>`,
  className: "",
  iconSize: [24, 32],
  iconAnchor: [12, 32],
  popupAnchor: [0, -34],
});

const DEFAULT_CENTER = {
  latitude: 1.3521,
  longitude: 103.8198,
};

// If VITE_MAPBOX_TOKEN is set in .env.local, Mapbox Streets tiles are used.
// Otherwise the map falls back to OpenStreetMap (no API key required).
const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN;

function openInMapsUrl(latitude, longitude, label) {
  const destination = encodeURIComponent(`${latitude},${longitude}`);
  const name = encodeURIComponent(label);
  return `https://www.google.com/maps/search/?api=1&query=${destination}%20(${name})`;
}

function MapViewportController({ listings, selectedListingId, userLocation, zoom }) {
  const map = useMap();

  useEffect(() => {
    const selectedListing = listings.find((listing) => listing.id === selectedListingId);

    if (selectedListing && selectedListing.latitude != null && selectedListing.longitude != null) {
      map.setView([selectedListing.latitude, selectedListing.longitude], zoom, {
        animate: true,
      });
      return;
    }

    const points = listings
      .filter((listing) => listing.latitude != null && listing.longitude != null)
      .map((listing) => [listing.latitude, listing.longitude]);

    if (userLocation) {
      points.push([userLocation.latitude, userLocation.longitude]);
    }

    if (points.length === 0) {
      return;
    }

    if (points.length === 1) {
      map.setView(points[0], zoom, { animate: true });
      return;
    }

    map.fitBounds(latLngBounds(points), { padding: [32, 32] });
  }, [listings, map, selectedListingId, userLocation, zoom]);

  return null;
}

export default function ListingLocationMap({
  listings,
  selectedListingId = null,
  onSelectListing,
  interactive = true,
  showUserLocation = false,
  className = "listing-location-map",
  zoom = 13,
}) {
  const [userLocation, setUserLocation] = useState(null);

  useEffect(() => {
    if (!showUserLocation || !navigator.geolocation) {
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        setUserLocation({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        });
      },
      () => {
        setUserLocation(null);
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 60000,
      }
    );
  }, [showUserLocation]);

  const mapCenter = useMemo(() => {
    const selectedListing = listings.find((listing) => listing.id === selectedListingId);

    if (selectedListing && selectedListing.latitude != null && selectedListing.longitude != null) {
      return [selectedListing.latitude, selectedListing.longitude];
    }

    const first = listings.find((l) => l.latitude != null && l.longitude != null);
    if (first) {
      return [first.latitude, first.longitude];
    }

    return [DEFAULT_CENTER.latitude, DEFAULT_CENTER.longitude];
  }, [listings, selectedListingId]);

  return (
    <MapContainer
      center={mapCenter}
      zoom={zoom}
      scrollWheelZoom={interactive}
      dragging={interactive}
      touchZoom={interactive}
      doubleClickZoom={interactive}
      boxZoom={interactive}
      keyboard={interactive}
      zoomControl={interactive}
      attributionControl
      className={className}
    >
      {MAPBOX_TOKEN ? (
        <TileLayer
          url={`https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/{z}/{x}/{y}@2x?access_token=${MAPBOX_TOKEN}`}
          attribution='Map data &copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a>, Imagery &copy; <a href="https://www.mapbox.com/">Mapbox</a>'
          tileSize={512}
          zoomOffset={-1}
        />
      ) : (
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
      )}

      <MapViewportController
        listings={listings}
        selectedListingId={selectedListingId}
        userLocation={userLocation}
        zoom={zoom}
      />

      {showUserLocation && userLocation && (
        <Marker
          position={[userLocation.latitude, userLocation.longitude]}
          icon={USER_PIN_ICON}
          zIndexOffset={1000}
        >
          <Popup>📍 You are here</Popup>
        </Marker>
      )}

      {listings.map((listing) => {
        const isSelected = listing.id === selectedListingId;

        return (
          <CircleMarker
            key={listing.id}
            center={[listing.latitude, listing.longitude]}
            radius={isSelected ? 11 : 7}
            eventHandlers={
              onSelectListing
                ? {
                    click: () => onSelectListing(listing.id),
                  }
                : undefined
            }
            pathOptions={{
              color: isSelected ? "#155b48" : "#ca5c2d",
              weight: isSelected ? 3 : 2,
              fillColor: isSelected ? "#1f9d75" : "#eb7c43",
              fillOpacity: isSelected ? 0.92 : 0.72,
            }}
          >
            <Popup>
              <div className="live-food-map__popup">
                <strong>{listing.name}</strong>
                <span>{listing.address}</span>
                <span>{listing.quantityLabel}</span>
                <a
                  href={openInMapsUrl(listing.latitude, listing.longitude, listing.name)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open in Google Maps
                </a>
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
