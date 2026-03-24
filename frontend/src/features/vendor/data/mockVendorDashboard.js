export const mockVendorListings = [
  {
    id: "vendor-listing-101",
    name: "Assorted Sourdough Loaves",
    quantity: 12,
    status: "CHARITY_ONLY",
    expiryLabel: "Expires today, 7:00 PM",
    pickupWindow: "4:30 PM - 7:00 PM",
    imageUrl:
      "https://images.unsplash.com/photo-1549931319-a545dcf3bc73?auto=format&fit=crop&w=1200&q=80",
    lastUpdatedLabel: "Updated 3 mins ago",
  },
  {
    id: "vendor-listing-102",
    name: "Fruit Yogurt Cups",
    quantity: 8,
    status: "PUBLIC_AVAILABLE",
    expiryLabel: "Expires today, 8:30 PM",
    pickupWindow: "5:00 PM - 8:00 PM",
    imageUrl:
      "https://images.unsplash.com/photo-1488477181946-6428a0291777?auto=format&fit=crop&w=1200&q=80",
    lastUpdatedLabel: "Moved to public tier 6 mins ago",
  },
  {
    id: "vendor-listing-103",
    name: "Chicken Rice Bento Sets",
    quantity: 4,
    status: "PENDING_COLLECTION",
    expiryLabel: "Collect before 6:45 PM",
    pickupWindow: "Now - 6:45 PM",
    imageUrl:
      "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=1200&q=80",
    lastUpdatedLabel: "Claimed by Hope Hands Charity",
  },
  {
    id: "vendor-listing-104",
    name: "Mini Blueberry Muffins",
    quantity: 6,
    status: "PAYMENT_PENDING",
    expiryLabel: "Pickup closes at 9:00 PM",
    pickupWindow: "6:00 PM - 9:00 PM",
    imageUrl:
      "https://images.unsplash.com/photo-1607958996333-41aef7caefaa?auto=format&fit=crop&w=1200&q=80",
    lastUpdatedLabel: "Awaiting public payment confirmation",
  },
  {
    id: "vendor-listing-105",
    name: "Mixed Vegetable Sandwiches",
    quantity: 0,
    status: "SOLD",
    expiryLabel: "Completed",
    pickupWindow: "Collection arranged",
    imageUrl:
      "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?auto=format&fit=crop&w=1200&q=80",
    lastUpdatedLabel: "Fully sold 18 mins ago",
  },
];

export const mockVendorNotifications = [
  {
    id: "notif-1",
    type: "claim",
    title: "Charity claim confirmed",
    message: "Hope Hands Charity claimed Chicken Rice Bento Sets.",
    timeLabel: "2 mins ago",
  },
  {
    id: "notif-2",
    type: "status",
    title: "Listing moved to public tier",
    message: "Fruit Yogurt Cups is now PUBLIC_AVAILABLE.",
    timeLabel: "6 mins ago",
  },
  {
    id: "notif-3",
    type: "purchase",
    title: "Public purchase in progress",
    message: "Mini Blueberry Muffins is waiting for payment confirmation.",
    timeLabel: "12 mins ago",
  },
];
