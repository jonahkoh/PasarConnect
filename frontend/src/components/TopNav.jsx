import { NavLink } from "react-router-dom";

export default function TopNav({ cartCount = 0 }) {
  return (
    <header className="topbar">
      <div className="brand">FoodLoop</div>

      <nav className="topbar__nav">
        <NavLink
          to="/marketplace/cart"
          className={({ isActive }) =>
            isActive ? "topbar__cart topbar__cart--active" : "topbar__cart"
          }
        >
          Cart
          <span className="topbar__cart-count">{cartCount}</span>
        </NavLink>

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
