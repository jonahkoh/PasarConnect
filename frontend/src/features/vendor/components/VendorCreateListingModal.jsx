import { useState } from "react";
import { createListing } from "../../../lib/listingApi";

const EMPTY = {
  title: "",
  description: "",
  quantity: "",
  weight_kg: "",
  expiry: "",
  image_url: "",
  latitude: "",
  longitude: "",
};

export default function VendorCreateListingModal({ token, onCreated, onClose }) {
  const [form, setForm] = useState(EMPTY);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  function set(field) {
    return (e) => setForm((prev) => ({ ...prev, [field]: e.target.value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setFormError("");

    if (!form.title.trim()) { setFormError("Title is required."); return; }
    if (!form.expiry)        { setFormError("Expiry date/time is required."); return; }
    if (!form.image_url.trim()) { setFormError("Image URL is required."); return; }
    if (!form.quantity.trim() && !form.weight_kg.trim()) {
      setFormError("Enter either quantity (units) or weight (kg)."); return;
    }

    const payload = {
      title:       form.title.trim(),
      description: form.description.trim() || undefined,
      image_url:   form.image_url.trim(),
      expiry:      new Date(form.expiry).toISOString(),
    };
    if (form.quantity.trim())  payload.quantity  = Number(form.quantity);
    if (form.weight_kg.trim()) payload.weight_kg = Number(form.weight_kg);
    if (form.latitude.trim())  payload.latitude  = Number(form.latitude);
    if (form.longitude.trim()) payload.longitude = Number(form.longitude);

    setIsSubmitting(true);
    try {
      const result = await createListing(payload, token);
      onCreated(result); // { listing_id, listed_at }
    } catch (err) {
      setFormError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-listing-title"
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "rgba(0,0,0,0.55)",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          background: "#fff", borderRadius: "12px", padding: "2rem",
          width: "min(540px, 95vw)", maxHeight: "90vh", overflowY: "auto",
          boxShadow: "0 8px 32px rgba(0,0,0,0.25)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
          <h2 id="create-listing-title" style={{ margin: 0, fontSize: "1.25rem" }}>Create New Listing</h2>
          <button
            type="button" onClick={onClose} aria-label="Close"
            style={{ background: "none", border: "none", fontSize: "1.5rem", cursor: "pointer", lineHeight: 1 }}
          >×</button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.9rem" }}>
            <span>Title *</span>
            <input
              type="text" value={form.title} onChange={set("title")}
              placeholder="e.g. Sourdough Loaves" required
              style={{ padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid #ccc" }}
            />
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.9rem" }}>
            <span>Description</span>
            <textarea
              value={form.description} onChange={set("description")} rows={2}
              placeholder="Optional — shown to charity/public users"
              style={{ padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid #ccc", resize: "vertical" }}
            />
          </label>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.9rem" }}>
              <span>Quantity (units)</span>
              <input
                type="number" min="1" value={form.quantity} onChange={set("quantity")}
                placeholder="e.g. 12"
                style={{ padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid #ccc" }}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.9rem" }}>
              <span>Weight (kg)</span>
              <input
                type="number" min="0.01" step="0.01" value={form.weight_kg} onChange={set("weight_kg")}
                placeholder="e.g. 2.5"
                style={{ padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid #ccc" }}
              />
            </label>
          </div>

          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.9rem" }}>
            <span>Expiry date &amp; time *</span>
            <input
              type="datetime-local" value={form.expiry} onChange={set("expiry")} required
              style={{ padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid #ccc" }}
            />
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.9rem" }}>
            <span>Image URL *</span>
            <input
              type="url" value={form.image_url} onChange={set("image_url")}
              placeholder="https://example.com/photo.jpg" required
              style={{ padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid #ccc" }}
            />
          </label>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.9rem" }}>
              <span>Latitude</span>
              <input
                type="number" step="any" value={form.latitude} onChange={set("latitude")}
                placeholder="e.g. 1.3521"
                style={{ padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid #ccc" }}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.9rem" }}>
              <span>Longitude</span>
              <input
                type="number" step="any" value={form.longitude} onChange={set("longitude")}
                placeholder="e.g. 103.8198"
                style={{ padding: "0.5rem 0.75rem", borderRadius: "6px", border: "1px solid #ccc" }}
              />
            </label>
          </div>

          {formError && (
            <p role="alert" style={{ color: "#c0392b", fontSize: "0.875rem", margin: 0 }}>{formError}</p>
          )}

          <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end", marginTop: "0.5rem" }}>
            <button
              type="button" onClick={onClose}
              style={{
                padding: "0.6rem 1.25rem", borderRadius: "6px",
                border: "1px solid #ccc", background: "#fff", cursor: "pointer",
              }}
            >Cancel</button>
            <button
              type="submit" disabled={isSubmitting}
              style={{
                padding: "0.6rem 1.25rem", borderRadius: "6px",
                background: "#1a1a2e", color: "#fff", border: "none", cursor: "pointer",
                opacity: isSubmitting ? 0.6 : 1,
              }}
            >{isSubmitting ? "Creating..." : "Create Listing"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
