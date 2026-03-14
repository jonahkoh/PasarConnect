import { useMemo, useState } from "react";
import TopNav from "../components/TopNav";
import PageHero from "../components/PageHero";
import SearchBar from "../components/SearchBar";
import FoodCard from "../components/FoodCard";
import { mockListings } from "../data/mockListings";

export default function CharityClaimPage() {
  const [listings, setListings] = useState(mockListings);
  const [search, setSearch] = useState("");
  const [claimingId, setClaimingId] = useState(null);
  const [message, setMessage] = useState("");

  const filteredListings = useMemo(() => {
    const keyword = search.trim().toLowerCase();

    return listings.filter((item) =>
      [item.name, item.vendor].some((value) =>
        value.toLowerCase().includes(keyword)
      )
    );
  }, [listings, search]);

  async function handleClaim(item) {
    setClaimingId(item.id);
    setMessage("");

    await new Promise((resolve) => setTimeout(resolve, 500));

    setListings((prev) => prev.filter((listing) => listing.id !== item.id));
    setClaimingId(null);
    setMessage(`You claimed "${item.name}".`);
  }

  return (
    <div className="app-shell">
      <TopNav />

      <main className="page charity-page">
        <PageHero
          icon="💙"
          title="Available Food Near You"
          subtitle="Claim items for free during the 30-minute charity priority window."
        />

        <SearchBar
          value={search}
          onChange={setSearch}
          placeholder="Search food items..."
        />

        {message && <div className="alert-success">{message}</div>}

        {filteredListings.length === 0 ? (
          <div className="empty-state">No matching food items found.</div>
        ) : (
          <section className="card-grid">
            {filteredListings.map((item) => (
              <FoodCard
                key={item.id}
                item={item}
                onAction={handleClaim}
                isProcessing={claimingId === item.id}
                actionLabel="Claim"
              />
            ))}
          </section>
        )}
      </main>
    </div>
  );
}