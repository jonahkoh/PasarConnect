export default function SearchBar({ value, onChange, placeholder }) {
  return (
    <div className="search-wrap">
      <input
        type="text"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="search-input"
      />
    </div>
  );
}