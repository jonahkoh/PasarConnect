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
