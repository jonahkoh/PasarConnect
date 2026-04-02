import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import TopNav from "../../../components/TopNav";
import { createVendorListing } from "../api/vendorApi";

const categoryOptions = [
  "Fresh Produce",
  "Fruit",
  "Bakery",
  "Prepared Meals",
  "Dairy & Soy",
];

const initialValues = {
  name: "",
  category: "",
  description: "",
  quantity: "",
  unitInfo: "",
  expiryDate: "",
  pickupDate: "",
  pickupWindow: "",
  pickupLocation: "",
  price: "",
  notes: "",
  imageFile: null,
};

function validate(values) {
  const errors = {};

  if (!values.name.trim()) {
    errors.name = "Enter the food item name.";
  }

  if (!values.category) {
    errors.category = "Select a category.";
  }

  if (!values.description.trim()) {
    errors.description = "Add a short description for this listing.";
  }

  if (!values.quantity) {
    errors.quantity = "Enter the quantity available.";
  } else if (Number(values.quantity) <= 0) {
    errors.quantity = "Quantity must be greater than 0.";
  }

  if (!values.unitInfo.trim()) {
    errors.unitInfo = "Add the unit or portion information.";
  }

  if (!values.expiryDate) {
    errors.expiryDate = "Select the expiry or best before date.";
  }

  if (!values.pickupDate) {
    errors.pickupDate = "Select the pickup date.";
  }

  if (
    values.expiryDate &&
    values.pickupDate &&
    values.pickupDate > values.expiryDate
  ) {
    errors.pickupDate = "Pickup date should be on or before the expiry date.";
  }

  if (!values.pickupWindow.trim()) {
    errors.pickupWindow = "Enter the pickup window.";
  }

  if (!values.pickupLocation.trim()) {
    errors.pickupLocation = "Enter the pickup location.";
  }

  if (values.price && Number(values.price) < 0) {
    errors.price = "Price cannot be negative.";
  }

  return errors;
}

export default function VendorCreateListingPage() {
  const navigate = useNavigate();
  const [values, setValues] = useState(initialValues);
  const [touched, setTouched] = useState({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [successMessage, setSuccessMessage] = useState("");
  const [submitError, setSubmitError] = useState("");

  const errors = useMemo(() => validate(values), [values]);
  const isFormValid =
    Object.keys(errors).length === 0 &&
    values.name.trim() &&
    values.category &&
    values.description.trim() &&
    values.quantity &&
    values.unitInfo.trim() &&
    values.expiryDate &&
    values.pickupDate &&
    values.pickupWindow.trim() &&
    values.pickupLocation.trim();

  function handleChange(event) {
    const { name, value, files } = event.target;

    setSuccessMessage("");
    setSubmitError("");
    setValues((prev) => ({
      ...prev,
      [name]: files ? files[0] ?? null : value,
    }));
  }

  function handleBlur(event) {
    setTouched((prev) => ({
      ...prev,
      [event.target.name]: true,
    }));
  }

  function getError(fieldName) {
    if (!errors[fieldName]) {
      return "";
    }

    if (submitAttempted || touched[fieldName]) {
      return errors[fieldName];
    }

    return "";
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitAttempted(true);
    setSuccessMessage("");
    setSubmitError("");

    if (Object.keys(errors).length > 0) {
      return;
    }

    setIsSubmitting(true);

    try {
      await createVendorListing(values);
      setSuccessMessage(
        "Listing created. It will enter the charity priority phase first and move to the public marketplace only if unclaimed."
      );
      setValues(initialValues);
      setTouched({});
      setSubmitAttempted(false);
    } catch (error) {
      setSubmitError(
        error?.message || "Unable to create the listing right now. Please try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="app-shell">
      <TopNav />

      <main className="page vendor-page">
        <Link to="/vendor" className="vendor-back-link">
          <span aria-hidden="true">←</span>
          <span>Back to vendor dashboard</span>
        </Link>

        <section className="vendor-hero">
          <div>
            <p className="vendor-eyebrow">Vendor Console</p>
            <h1>Create New Listing</h1>
            <p className="vendor-hero__copy">
              Add surplus food details for redistribution. New listings enter the
              charity priority phase first before any unclaimed items move to the
              public marketplace.
            </p>
          </div>
        </section>

        {successMessage ? (
          <div className="alert-success" role="status">
            {successMessage}
          </div>
        ) : null}

        {submitError ? (
          <div className="vendor-error-banner" role="alert">
            {submitError}
          </div>
        ) : null}

        <section className="vendor-create-layout">
          <section className="vendor-create-panel">
            <div className="vendor-panel__header">
              <div>
                <h2>Listing Details</h2>
                <p>Fields marked with * are required before submission.</p>
              </div>
            </div>

            <form className="vendor-create-form" onSubmit={handleSubmit} noValidate>
              <div className="vendor-create-form__grid">
                <label className="vendor-form-field vendor-form-field--full">
                  <span>Food item name *</span>
                  <input
                    type="text"
                    name="name"
                    value={values.name}
                    onChange={handleChange}
                    onBlur={handleBlur}
                    placeholder="e.g. Assorted bread tray"
                  />
                  {getError("name") ? (
                    <small className="vendor-form-field__error">
                      {getError("name")}
                    </small>
                  ) : null}
                </label>

                <label className="vendor-form-field">
                  <span>Category *</span>
                  <select
                    name="category"
                    value={values.category}
                    onChange={handleChange}
                    onBlur={handleBlur}
                  >
                    <option value="">Select a category</option>
                    {categoryOptions.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                  {getError("category") ? (
                    <small className="vendor-form-field__error">
                      {getError("category")}
                    </small>
                  ) : null}
                </label>

                <label className="vendor-form-field">
                  <span>Quantity *</span>
                  <input
                    type="number"
                    min="1"
                    name="quantity"
                    value={values.quantity}
                    onChange={handleChange}
                    onBlur={handleBlur}
                    placeholder="e.g. 12"
                  />
                  {getError("quantity") ? (
                    <small className="vendor-form-field__error">
                      {getError("quantity")}
                    </small>
                  ) : null}
                </label>

                <label className="vendor-form-field">
                  <span>Unit or portion info *</span>
                  <input
                    type="text"
                    name="unitInfo"
                    value={values.unitInfo}
                    onChange={handleChange}
                    onBlur={handleBlur}
                    placeholder="e.g. loaves, packs, trays"
                  />
                  {getError("unitInfo") ? (
                    <small className="vendor-form-field__error">
                      {getError("unitInfo")}
                    </small>
                  ) : null}
                </label>

                <label className="vendor-form-field">
                  <span>Expiry / best before date *</span>
                  <input
                    type="date"
                    name="expiryDate"
                    value={values.expiryDate}
                    onChange={handleChange}
                    onBlur={handleBlur}
                  />
                  {getError("expiryDate") ? (
                    <small className="vendor-form-field__error">
                      {getError("expiryDate")}
                    </small>
                  ) : null}
                </label>

                <label className="vendor-form-field">
                  <span>Pickup date *</span>
                  <input
                    type="date"
                    name="pickupDate"
                    value={values.pickupDate}
                    onChange={handleChange}
                    onBlur={handleBlur}
                  />
                  {getError("pickupDate") ? (
                    <small className="vendor-form-field__error">
                      {getError("pickupDate")}
                    </small>
                  ) : null}
                </label>

                <label className="vendor-form-field vendor-form-field--full">
                  <span>Pickup window *</span>
                  <input
                    type="text"
                    name="pickupWindow"
                    value={values.pickupWindow}
                    onChange={handleChange}
                    onBlur={handleBlur}
                    placeholder="e.g. 4:30 PM - 7:00 PM"
                  />
                  {getError("pickupWindow") ? (
                    <small className="vendor-form-field__error">
                      {getError("pickupWindow")}
                    </small>
                  ) : null}
                </label>

                <label className="vendor-form-field vendor-form-field--full">
                  <span>Pickup location *</span>
                  <input
                    type="text"
                    name="pickupLocation"
                    value={values.pickupLocation}
                    onChange={handleChange}
                    onBlur={handleBlur}
                    placeholder="e.g. Stall 03-18, Tiong Bahru Market"
                  />
                  {getError("pickupLocation") ? (
                    <small className="vendor-form-field__error">
                      {getError("pickupLocation")}
                    </small>
                  ) : null}
                </label>

                <label className="vendor-form-field">
                  <span>Discounted price</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    name="price"
                    value={values.price}
                    onChange={handleChange}
                    onBlur={handleBlur}
                    placeholder="e.g. 3.50"
                  />
                  {getError("price") ? (
                    <small className="vendor-form-field__error">
                      {getError("price")}
                    </small>
                  ) : (
                    <small className="vendor-form-field__hint">
                      Leave blank if the item is free during redistribution.
                    </small>
                  )}
                </label>

                <label className="vendor-form-field">
                  <span>Image upload</span>
                  <input
                    type="file"
                    name="imageFile"
                    accept="image/*"
                    capture="environment"
                    onChange={handleChange}
                    onBlur={handleBlur}
                  />
                  <small className="vendor-form-field__hint">
                    Upload an image or take a photo on supported mobile devices.
                  </small>
                </label>

                <label className="vendor-form-field vendor-form-field--full">
                  <span>Description *</span>
                  <textarea
                    name="description"
                    rows="4"
                    value={values.description}
                    onChange={handleChange}
                    onBlur={handleBlur}
                    placeholder="Briefly describe the food type, packaging, and collection condition."
                  />
                  {getError("description") ? (
                    <small className="vendor-form-field__error">
                      {getError("description")}
                    </small>
                  ) : null}
                </label>

                <label className="vendor-form-field vendor-form-field--full">
                  <span>Optional notes</span>
                  <textarea
                    name="notes"
                    rows="3"
                    value={values.notes}
                    onChange={handleChange}
                    onBlur={handleBlur}
                    placeholder="Add pickup instructions or handling notes if needed."
                  />
                </label>
              </div>

              <div className="vendor-create-form__actions">
                <button
                  type="button"
                  className="vendor-secondary-button"
                  onClick={() => navigate("/vendor")}
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  className="vendor-primary-button"
                  disabled={!isFormValid || isSubmitting}
                >
                  {isSubmitting ? "Creating..." : "Create Listing"}
                </button>
              </div>
            </form>
          </section>

          <aside className="vendor-create-sidebar">
            <section className="vendor-create-info-card">
              <p className="vendor-eyebrow">Listing Flow</p>
              <h2>What happens next</h2>
              <ul className="vendor-create-info-card__list">
                <li>New listings are shown to registered charities first.</li>
                <li>Unclaimed listings can then move into the public marketplace.</li>
                <li>Accurate pickup and expiry details help prevent food waste.</li>
              </ul>
            </section>

            <section className="vendor-create-info-card">
              <p className="vendor-eyebrow">Backend Status</p>
              <h2>Mock submit in use</h2>
              <p className="vendor-create-info-card__copy">
                This page currently uses a mock create function. Replace
                `createVendorListing()` in the vendor API layer when the backend
                endpoint is available.
              </p>
            </section>
          </aside>
        </section>
      </main>
    </div>
  );
}
