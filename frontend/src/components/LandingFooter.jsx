import { Link } from "react-router-dom";

const navigationLinks = [
  { label: "Home", href: "/#home", type: "anchor" },
  { label: "How It Works", href: "/#how-it-works", type: "anchor" },
  { label: "Impact", href: "/#impact", type: "anchor" },
];

const actionLinks = [
  { label: "Login", href: "/login", type: "route" },
];

export default function LandingFooter() {
  return (
    <footer className="landing-footer">
      <div className="landing-footer__card">
        <div className="landing-footer__content">
          <div className="landing-footer__brand">
            <div className="landing-footer__brand-row">
              <img
                src="/pasarconnect-logo.svg"
                alt="PasarConnect"
                className="landing-footer__logo"
              />
              <p className="landing-footer__eyebrow">PasarConnect</p>
            </div>

            <h2>Reducing food waste through practical community redistribution.</h2>
            <p className="landing-footer__copy">
              PasarConnect helps vendors share surplus food, gives charities
              priority access, and opens remaining items to the public when they
              would otherwise go to waste.
            </p>

            <a href="/#home" className="landing-footer__back-top">
              ↑ Back to top
            </a>
          </div>

          <div className="landing-footer__nav-group">
            <p className="landing-footer__label">Navigate</p>
            <nav className="landing-footer__links" aria-label="Footer navigation">
              {navigationLinks.map((link) => (
                <a key={link.label} href={link.href}>
                  {link.label}
                </a>
              ))}
            </nav>
          </div>

          <div className="landing-footer__nav-group">
            <p className="landing-footer__label">Access</p>
            <nav className="landing-footer__links" aria-label="Footer account links">
              {actionLinks.map((link) => (
                <Link key={link.label} to={link.href}>
                  {link.label}
                </Link>
              ))}
            </nav>
          </div>
        </div>

        <div className="landing-footer__meta">
          <span>PasarConnect for vendors, charities, and communities.</span>
          <span>Designed for practical surplus-food redistribution.</span>
        </div>
      </div>
    </footer>
  );
}
