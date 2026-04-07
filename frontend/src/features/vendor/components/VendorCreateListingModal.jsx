import { useRef, useState } from "react";
import { createListing } from "../../../lib/listingApi";
import { getPresignedUrl, uploadToS3 } from "../../../lib/mediaApi";

const EMPTY = {
  title: "",
  description: "",
  quantity: "",
  weight_kg: "",
  expiry: "",
  image_url: "",   // populated automatically after S3 upload
  latitude: "",
  longitude: "",
};

const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10 MB

export default function VendorCreateListingModal({ token, onCreated, onClose }) {
  const [form, setForm] = useState(EMPTY);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  // Upload state: "idle" | "uploading" | "done" | "error"
  const [uploadState, setUploadState]       = useState("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError]       = useState("");
  const [previewUrl, setPreviewUrl]         = useState("");

  const fileInputRef = useRef(null);

  function set(field) {
    return (e) => setForm((prev) => ({ ...prev, [field]: e.target.value }));
  }

  async function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > MAX_FILE_BYTES) {
      setUploadError("File too large — please choose an image under 10 MB.");
      setUploadState("error");
      return;
    }

    // Show a local preview immediately.
    setPreviewUrl(URL.createObjectURL(file));
    setUploadState("uploading");
    setUploadProgress(0);
    setUploadError("");
    setForm((prev) => ({ ...prev, image_url: "" }));

    try {
      const { upload_url, public_url } = await getPresignedUrl(file.name, file.type, token);
      await uploadToS3(file, upload_url, setUploadProgress);
      setForm((prev) => ({ ...prev, image_url: public_url }));
      setUploadState("done");
    } catch (err) {
      setUploadState("error");
      setUploadError(err.message || "Upload failed. Please try again.");
    }
  }

  function handleRemovePhoto() {
    setForm((prev) => ({ ...prev, image_url: "" }));
    setPreviewUrl("");
    setUploadState("idle");
    setUploadProgress(0);
    setUploadError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setFormError("");

    if (!form.title.trim())  { setFormError("Title is required."); return; }
    if (!form.expiry)        { setFormError("Expiry date & time is required."); return; }
    if (uploadState === "uploading") { setFormError("Please wait for the photo to finish uploading."); return; }
    if (!form.image_url)     { setFormError("A photo is required — choose one above."); return; }
    if (!form.quantity.trim() && !form.weight_kg.trim()) {
      setFormError("Enter either quantity (units) or weight (kg)."); return;
    }

    const payload = {
      title:       form.title.trim(),
      description: form.description.trim() || undefined,
      image_url:   form.image_url,
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

            {/* ── Photo upload ── */}
            <div className="vendor-form-field">
              <span className="vendor-form-label">Photo *</span>

              {/* Hidden native file input — triggered by the button below */}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleFileChange}
                style={{ display: "none" }}
                aria-label="Choose a photo"
              />

              {uploadState === "done" && form.image_url ? (
                /* ── Preview after successful upload ── */
                <div className="vendor-upload-preview">
                  <img
                    src={previewUrl || form.image_url}
                    alt="Listing preview"
                    className="vendor-upload-preview__img"
                  />
                  <button
                    type="button"
                    className="vendor-upload-preview__remove"
                    onClick={handleRemovePhoto}
                  >
                    Change photo
                  </button>
                </div>
              ) : uploadState === "uploading" ? (
                /* ── Progress bar ── */
                <div className="vendor-upload-progress">
                  <div className="vendor-upload-progress__bar">
                    <div
                      className="vendor-upload-progress__fill"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                  <span className="vendor-upload-progress__label">
                    Uploading… {uploadProgress}%
                  </span>
                </div>
              ) : (
                /* ── Pick / capture button ── */
                <button
                  type="button"
                  className="vendor-upload-btn"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploadState === "uploading"}
                >
                  <span className="vendor-upload-btn__icon">📷</span>
                  <span>Take a photo or choose from gallery</span>
                </button>
              )}

              {uploadState === "error" && uploadError && (
                <p className="vendor-form-error" role="alert">{uploadError}</p>
              )}
            </div>
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
            <button
              type="submit"
              disabled={isSubmitting || uploadState === "uploading"}
              className="vendor-modal__submit"
            >
              {isSubmitting ? "Creating…" : "Create Listing"}
            </button>
          </div>

        </form>
      </div>
    </div>
  );
}

