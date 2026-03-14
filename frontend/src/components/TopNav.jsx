import { NavLink } from "react-router-dom";

export default function TopNav() {
  return (
    <header className="topbar">
      <div className="brand">FoodLoop</div>

      <nav className="topbar__nav">
        <span>🛒</span>

        <NavLink
          to="/charity"
          className={({ isActive }) =>
            isActive ? "topbar__link topbar__link--active" : "topbar__link"
          }
        >
          Charity
        </NavLink>

        <NavLink
          to="/marketplace"
          className={({ isActive }) =>
            isActive ? "topbar__link topbar__link--active" : "topbar__link"
          }
        >
          Marketplace
        </NavLink>

        <button className="topbar__signout" type="button">
          Sign Out
        </button>
      </nav>
    </header>
  );
}