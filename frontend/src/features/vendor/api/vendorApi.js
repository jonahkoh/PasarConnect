import {
  mockVendorListings,
  mockVendorNotifications,
} from "../data/mockVendorDashboard";

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function fetchVendorDashboard() {
  // Replace this mock with a real Inventory Service call when the endpoint is ready.
  await wait(450);

  return {
    listings: mockVendorListings,
    notifications: mockVendorNotifications,
  };
}

export async function createVendorListing(formValues) {
  // Replace this mock with a real Inventory Service create-listing call
  // once the backend endpoint and request payload are confirmed.
  await wait(500);

  return {
    id: `vendor-listing-${Date.now()}`,
    name: formValues.name.trim(),
    category: formValues.category,
    description: formValues.description.trim(),
    quantity: Number(formValues.quantity),
    unitInfo: formValues.unitInfo.trim(),
    expiryDate: formValues.expiryDate,
    pickupDate: formValues.pickupDate,
    pickupWindow: formValues.pickupWindow.trim(),
    pickupLocation: formValues.pickupLocation.trim(),
    price: formValues.price ? Number(formValues.price) : null,
    notes: formValues.notes.trim(),
    imageFileName: formValues.imageFile?.name ?? null,
    status: "CHARITY_ONLY",
  };
}
