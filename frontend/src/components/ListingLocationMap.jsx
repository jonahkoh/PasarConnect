import { useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import { latLngBounds } from "leaflet";
import "leaflet/dist/leaflet.css";

const DEFAULT_CENTER = {
  latitude: 1.3521,
  longitude: 103.8198,
};

function openInMapsUrl(latitude, longitude, label) {
  const destination = encodeURIComponent(`${latitude},${longitude}`);
  const name = encodeURIComponent(label);
  return `https://www.google.com/maps/search/?api=1&query=${destination}%20(${name})`;
}

function MapViewportController({ listings, selectedListingId, userLocation, zoom }) {
  const map = useMap();

  useEffect(() => {
    const selectedListing = listings.find((listing) => listing.id === selectedListingId);

    if (selectedListing) {
      map.setView([selectedListing.latitude, selectedListing.longitude], zoom, {
        animate: true,
      });
      return;
    }

    const points = listings.map((listing) => [listing.latitude, listing.longitude]);

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

    if (selectedListing) {
      return [selectedListing.latitude, selectedListing.longitude];
    }

    if (listings.length > 0) {
      return [listings[0].latitude, listings[0].longitude];
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
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      <MapViewportController
        listings={listings}
        selectedListingId={selectedListingId}
        userLocation={userLocation}
        zoom={zoom}
      />

      {showUserLocation && userLocation && (
        <CircleMarker
          center={[userLocation.latitude, userLocation.longitude]}
          radius={9}
          pathOptions={{
            color: "#165b49",
            weight: 2,
            fillColor: "#48bc90",
            fillOpacity: 0.9,
          }}
        >
          <Popup>You are here</Popup>
        </CircleMarker>
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
