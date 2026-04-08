import { useCallback, useEffect, useRef, useState } from "react";
import { searchOneMapPlaces } from "../lib/onemapApi";

/**
 * LocationPicker
 *
 * A composable location input that combines:
 *   - Debounced OneMap place search as the user types
 *   - A "Use my current location" GPS button
 *   - An auto-fill "Current Location" option in the dropdown when GPS is already granted
 *
 * Props:
 *   onSelect({ lat, lng })  — called when a location is confirmed
 *   initialLabel            — string to pre-fill the input (cosmetic only)
 */
export default function LocationPicker({ onSelect, initialLabel = "" }) {
  const [query, setQuery]           = useState(initialLabel);
  const [suggestions, setSuggestions] = useState([]);
  const [isOpen, setIsOpen]         = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [gpsLoading, setGpsLoading]  = useState(false);
  const [gpsDenied, setGpsDenied]    = useState(false);
  const [gpsCoords, setGpsCoords]    = useState(null); // { lat, lng }

  const debounceRef = useRef(null);
  const abortRef    = useRef(null);
  const wrapRef     = useRef(null);

  // ── Close dropdown when clicking outside ─────────────────────────────────
  useEffect(() => {
    function handleOut(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOut);
    return () => document.removeEventListener("mousedown", handleOut);
  }, []);

  // ── Text search (debounced 300 ms) ────────────────────────────────────────
  const doSearch = useCallback(async (value) => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();
    setIsSearching(true);
    try {
      const results = await searchOneMapPlaces(value, { signal: abortRef.current.signal });
      setSuggestions(results);
      setIsOpen(true);
    } catch (err) {
      if (err.name !== "AbortError") setSuggestions([]);
    } finally {
      setIsSearching(false);
    }
  }, []);

  function handleInputChange(e) {
    const val = e.target.value;
    setQuery(val);

    clearTimeout(debounceRef.current);

    if (!val.trim()) {
      setSuggestions([]);
      // If we have GPS, show the "use current location" option when field is cleared
      setIsOpen(!!gpsCoords);
      return;
    }

    debounceRef.current = setTimeout(() => doSearch(val), 300);
  }

  function handleFocus() {
    // Show GPS option immediately when field is focused with no text
    if (!query.trim() && gpsCoords) {
      setIsOpen(true);
      return;
    }
    if (suggestions.length > 0) setIsOpen(true);
  }

  // ── Select a suggestion from the dropdown ─────────────────────────────────
  function handleSelect(item) {
    setQuery(item.label);
    setSuggestions([]);
    setIsOpen(false);
    onSelect({ lat: item.lat, lng: item.lng });
  }

  // ── Use GPS current location ──────────────────────────────────────────────
  function handleUseGPS() {
    // If we already have coords, reuse them immediately
    if (gpsCoords) {
      setQuery("📍 Current Location");
      setIsOpen(false);
      onSelect(gpsCoords);
      return;
    }

    setGpsLoading(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const loc = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setGpsCoords(loc);
        setGpsLoading(false);
        setGpsDenied(false);
        setQuery("📍 Current Location");
        setIsOpen(false);
        onSelect(loc);
      },
      () => {
        setGpsLoading(false);
        setGpsDenied(true);
      },
      { enableHighAccuracy: true, timeout: 8000 }
    );
  }

  // ── Confirm current-location option from dropdown ─────────────────────────
  function handleSelectGPS(e) {
    e.preventDefault(); // prevent input blur from closing dropdown first
    setQuery("📍 Current Location");
    setIsOpen(false);
    onSelect(gpsCoords);
  }

  return (
    <div className="loc-picker" ref={wrapRef}>
      {/* ── Input row ─────────────────────────────────────────────────── */}
      <div className="loc-picker__row">
        <div className="loc-picker__input-wrap">
          <span className="loc-picker__pin" aria-hidden="true">🗺</span>
          <input
            type="text"
            className="loc-picker__input"
            placeholder="Search for your location…"
            value={query}
            onChange={handleInputChange}
            onFocus={handleFocus}
            autoComplete="off"
            aria-label="Location search"
            aria-autocomplete="list"
            aria-expanded={isOpen}
          />
          {isSearching && (
            <span className="loc-picker__spin" aria-label="Searching…" />
          )}
        </div>

        <button
          type="button"
          className={`loc-picker__gps-btn${gpsLoading ? " loc-picker__gps-btn--loading" : ""}`}
          onClick={handleUseGPS}
          disabled={gpsLoading}
          title="Use my current location"
          aria-label="Use my current location"
        >
          🎯
        </button>
      </div>

      {/* ── Permission denied warning ─────────────────────────────────── */}
      {gpsDenied && (
        <p className="loc-picker__denied" role="alert">
          Location access denied — search above, or enable location in your
          browser settings.
        </p>
      )}

      {/* ── Dropdown ──────────────────────────────────────────────────── */}
      {isOpen && (gpsCoords || suggestions.length > 0) && (
        <ul className="loc-picker__dropdown" role="listbox">

          {/* GPS option — shown at top when coords are available */}
          {gpsCoords && (
            <li
              className="loc-picker__option loc-picker__option--gps"
              role="option"
              onMouseDown={handleSelectGPS}
            >
              <span className="loc-picker__option-icon">📍</span>
              <span className="loc-picker__option-text">
                <strong>Use my current location</strong>
              </span>
            </li>
          )}

          {suggestions.map((s, i) => (
            <li
              key={i}
              className="loc-picker__option"
              role="option"
              onMouseDown={(e) => { e.preventDefault(); handleSelect(s); }}
            >
              <span className="loc-picker__option-icon">🏢</span>
              <span className="loc-picker__option-text">
                {s.building ? (
                  <>
                    <strong className="loc-picker__option-name">{s.building}</strong>
                    <span className="loc-picker__option-addr">{s.label}</span>
                  </>
                ) : (
                  <span className="loc-picker__option-name">{s.label}</span>
                )}
              </span>
            </li>
          ))}

          {!gpsCoords && suggestions.length === 0 && query.trim() && !isSearching && (
            <li className="loc-picker__option loc-picker__option--empty" aria-disabled="true">
              No results found
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
