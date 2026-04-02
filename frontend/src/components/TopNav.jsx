import { Link } from "react-router-dom";

export default function TopNav() {
  return (
    <header className="topbar">
      <a href="/#home" className="brand">
        <img
          src="/pasarconnect-logo.svg"
          alt="PasarConnect"
          className="brand__logo"
        />
        <span className="brand__text">PasarConnect</span>
      </a>

      <nav className="topbar__nav" aria-label="Primary navigation">
        <a href="/#home" className="topbar__link">
          Home
        </a>
        <a href="/#how-it-works" className="topbar__link">
          How It Works
        </a>
        <a href="/#impact" className="topbar__link">
          Impact
        </a>
      </nav>

      <div className="topbar__actions">
        <Link to="/login" className="topbar__login">
          Login
        </Link>
      </div>
    </header>
  );
}
