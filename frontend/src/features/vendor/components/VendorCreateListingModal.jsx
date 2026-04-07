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
    if (!form.expiry)        { setFormError("Expiry date & time is required."); return; }
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
      onCreated(result);
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
      className="vendor-modal-backdrop"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="vendor-modal">

        {/* Sticky header */}
        <div className="vendor-modal__head">
          <h2 id="create-listing-title" className="vendor-modal__title">Create New Listing</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="vendor-modal__close">
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit} className="vendor-modal__body">

          {/* Section 1 — What are you listing? */}
          <div className="vendor-modal__section">
            <p className="vendor-modal__section-title">What are you listing?</p>

            <label className="vendor-form-field">
              <span className="vendor-form-label">Title *</span>
              <input
                type="text" value={form.title} onChange={set("title")}
                placeholder="e.g. Sourdough Loaves" required
                className="vendor-form-input"
              />
            </label>

            <label className="vendor-form-field">
              <span className="vendor-form-label">Description</span>
              <textarea
                value={form.description} onChange={set("description")} rows={2}
                placeholder="Optional — shown to charity and public users"
                className="vendor-form-textarea"
              />
            </label>

            <label className="vendor-form-field">
              <span className="vendor-form-label">Image URL *</span>
              <input
                type="url" value={form.image_url} onChange={set("image_url")}
                placeholder="https://example.com/photo.jpg" required
                className="vendor-form-input"
              />
            </label>
          </div>

          {/* Section 2 — Quantity */}
          <div className="vendor-modal__section">
            <p className="vendor-modal__section-title">Quantity</p>
            <p className="vendor-form-hint">Fill in at least one — units for countable items (e.g. loaves), kg for loose food (e.g. rice).</p>

            <div className="vendor-form-row">
              <label className="vendor-form-field">
                <span className="vendor-form-label">Units</span>
                <input
                  type="number" min="1" value={form.quantity} onChange={set("quantity")}
                  placeholder="e.g. 12"
                  className="vendor-form-input"
                />
              </label>
              <label className="vendor-form-field">
                <span className="vendor-form-label">Weight (kg)</span>
                <input
                  type="number" min="0.01" step="0.01" value={form.weight_kg} onChange={set("weight_kg")}
                  placeholder="e.g. 2.5"
                  className="vendor-form-input"
                />
              </label>
            </div>
          </div>

          {/* Section 3 — When & where? */}
          <div className="vendor-modal__section">
            <p className="vendor-modal__section-title">When &amp; where?</p>

            <label className="vendor-form-field">
              <span className="vendor-form-label">Expiry date &amp; time *</span>
              <input
                type="datetime-local" value={form.expiry} onChange={set("expiry")} required
                className="vendor-form-input"
              />
            </label>

            <div className="vendor-form-row">
              <label className="vendor-form-field">
                <span className="vendor-form-label">Latitude</span>
                <input
                  type="number" step="any" value={form.latitude} onChange={set("latitude")}
                  placeholder="e.g. 1.3521"
                  className="vendor-form-input"
                />
              </label>
              <label className="vendor-form-field">
                <span className="vendor-form-label">Longitude</span>
                <input
                  type="number" step="any" value={form.longitude} onChange={set("longitude")}
                  placeholder="e.g. 103.8198"
                  className="vendor-form-input"
                />
              </label>
            </div>
            <p className="vendor-form-hint">Location is optional — leave blank if you prefer not to show a map pin.</p>
          </div>

          {formError && (
            <p role="alert" className="vendor-form-error">{formError}</p>
          )}

          <div className="vendor-modal__actions">
            <button type="button" onClick={onClose} className="vendor-modal__cancel">
              Cancel
            </button>
            <button type="submit" disabled={isSubmitting} className="vendor-modal__submit">
              {isSubmitting ? "Creating…" : "Create Listing"}
            </button>
          </div>

        </form>
      </div>
    </div>
  );
}

