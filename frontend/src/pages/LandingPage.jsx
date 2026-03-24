import { Link } from "react-router-dom";
import TopNav from "../components/TopNav";

const roleCards = [
  {
    title: "Vendor",
    description:
      "Create surplus food listings, track statuses, and manage active items from one dashboard.",
    to: "/vendor",
    cta: "Go to Vendor Dashboard",
  },
  {
    title: "Charity",
    description:
      "Browse newly listed items and claim food during the charity priority window.",
    to: "/charity",
    cta: "Open Charity View",
  },
  {
    title: "Marketplace",
    description:
      "Browse discounted surplus food after the charity phase closes and purchase available items.",
    to: "/marketplace",
    cta: "Browse Marketplace",
  },
];

const steps = [
  {
    title: "Vendors list surplus food",
    description:
      "Food businesses post items nearing expiry with quantity and pickup details.",
  },
  {
    title: "Charities get priority access",
    description:
      "Registered charities can claim available food first during the limited access window.",
  },
  {
    title: "Public users buy what remains",
    description:
      "If items are not claimed, they move into the public marketplace at discounted prices.",
  },
];

export default function LandingPage() {
  return (
    <div className="app-shell landing-shell">
      <TopNav />

      <main className="landing-page">
        <section id="home" className="landing-hero">
          <div className="landing-hero__content">
            <p className="landing-eyebrow">PasarConnect</p>
            <h1>
              Turn surplus food into
              <br />
              community impact.
            </h1>
            <p className="landing-hero__copy">
              One platform for vendors, charities, and public users to reduce food waste through a simple redistribution flow.
            </p>
          </div>

          <div className="landing-hero__panel">
            <div className="landing-highlight-card">
              <h2>Less waste</h2>
              <p>Useful food is redirected before it is thrown away.</p>
            </div>
            <div className="landing-highlight-card">
              <h2>More access</h2>
              <p>Charities and public users can access food through clear phases.</p>
            </div>
            <div className="landing-highlight-card">
              <h2>Simple flow</h2>
              <p>The platform keeps the redistribution lifecycle easy to follow.</p>
            </div>
          </div>
        </section>

        <section className="landing-section">
          <div className="landing-section__header">
            <p className="landing-eyebrow">Choose Your View</p>
            <h2>Start from the role that matches what you need to do.</h2>
          </div>

          <div className="landing-role-grid">
            {roleCards.map((role) => (
              <Link
                key={role.title}
                to={role.to}
                className="landing-role-card"
                aria-label={role.cta}
              >
                <div className="landing-role-card__header">
                  <h3>{role.title}</h3>
                  <span className="landing-role-card__arrow" aria-hidden="true">
                    →
                  </span>
                </div>
                <p>{role.description}</p>
              </Link>
            ))}
          </div>
        </section>

        <section id="how-it-works" className="landing-section">
          <div className="landing-section__header">
            <p className="landing-eyebrow">How It Works</p>
            <h2>A simple 3-step redistribution flow.</h2>
          </div>

          <div className="landing-step-grid">
            {steps.map((step, index) => (
              <article key={step.title} className="landing-step-card">
                <span className="landing-step-card__number">0{index + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.description}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="impact" className="landing-impact">
          <div>
            <p className="landing-eyebrow landing-eyebrow--light">Why It Matters</p>
            <h2>Reducing food waste can also improve food access.</h2>
            <p>
              PasarConnect is designed to make surplus-food redistribution
              practical, visible, and easy to understand. It supports vendors,
              helps charities respond faster, and gives public users affordable
              access to good food.
            </p>
          </div>
        </section>

        <footer className="landing-footer">
          <p>PasarConnect</p>
          <span>Reducing food waste through practical community redistribution.</span>
        </footer>
      </main>
    </div>
  );
}
