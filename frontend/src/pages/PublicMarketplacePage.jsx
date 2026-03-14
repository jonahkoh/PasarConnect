import { useMemo, useState } from "react";
import TopNav from "../components/TopNav";
import PageHero from "../components/PageHero";
import SearchBar from "../components/SearchBar";
import FoodCard from "../components/FoodCard";
import { mockPublicListings } from "../data/mockPublicListings";

export default function PublicMarketplacePage() {
  const [listings, setListings] = useState(mockPublicListings);
  const [search, setSearch] = useState("");
  const [buyingId, setBuyingId] = useState(null);
  const [message, setMessage] = useState("");

  const filteredListings = useMemo(() => {
    const keyword = search.trim().toLowerCase();

    return listings.filter((item) =>
      [item.name, item.vendor].some((value) =>
        value.toLowerCase().includes(keyword)
      )
    );
  }, [listings, search]);

  async function handleBuy(item) {
    setBuyingId(item.id);
    setMessage("");

    await new Promise((resolve) => setTimeout(resolve, 500));

    setListings((prev) => prev.filter((listing) => listing.id !== item.id));
    setBuyingId(null);
    setMessage(`You purchased "${item.name}".`);
  }

  return (
    <div className="app-shell">
      <TopNav />

      <main className="page">
        <PageHero
          icon="🛍️"
          title="Public Marketplace"
          subtitle="Browse discounted food listings after the charity window closes."
        />

        <SearchBar
          value={search}
          onChange={setSearch}
          placeholder="Search marketplace items..."
        />

        {message && <div className="alert-success">{message}</div>}

        {filteredListings.length === 0 ? (
          <div className="empty-state">No matching marketplace items found.</div>
        ) : (
          <section className="card-grid">
            {filteredListings.map((item) => (
              <FoodCard
                key={item.id}
                item={item}
                onAction={handleBuy}
                isProcessing={buyingId === item.id}
                actionLabel="Buy"
              />
            ))}
          </section>
        )}
      </main>
    </div>
  );
}