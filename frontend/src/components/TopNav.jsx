export default function TopNav() {
  return (
    <header className="topbar">
      <a href="/#home" className="brand">
        PasarConnect
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
        <a href="/login" className="topbar__link">
          Login
        </a>
      </div>
    </header>
  );
}
