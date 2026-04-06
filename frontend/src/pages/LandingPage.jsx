import { Link } from "react-router-dom";
import TopNav from "../components/TopNav";

const roleCards = [
  {
    title: "Vendor",
    description:
      "List surplus food, keep track of active items, and manage redistribution from one dashboard.",
    to: "/login?role=vendor",
    cta: "Continue as Vendor",
    eyebrow: "For food businesses",
  },
  {
    title: "Charity",
    description:
      "Review new listings and claim available food during the charity priority window.",
    to: "/login?role=charity",
    cta: "Continue as Charity",
    eyebrow: "For registered charities",
  },
  {
    title: "Marketplace",
    description:
      "Browse and buy discounted food after the charity phase closes and listings move public.",
    to: "/login?role=marketplace",
    cta: "Continue as Public User",
    eyebrow: "For the public",
  },
];

const highlightCards = [
  {
    title: "Less waste",
    description: "Redirect useful food before it gets thrown away.",
  },
  {
    title: "Faster access",
    description: "Give charities a clear first-access window for urgent redistribution.",
  },
  {
    title: "Practical marketplace",
    description: "Open unclaimed listings to public users at more affordable prices.",
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

const impactPoints = [
  "Reduce avoidable food waste across vendors and neighbourhoods.",
  "Help charities respond earlier to available surplus food.",
  "Improve access to affordable food through a clear public marketplace phase.",
];

export default function LandingPage() {
  return (
    <div className="app-shell landing-shell">
      <TopNav />

      <main className="landing-page">
        <section id="home" className="landing-hero">
          <div className="landing-hero__content">
            <p className="landing-eyebrow">Food redistribution for vendors, charities, and communities</p>
            <h1>Move surplus food to the people who can use it.</h1>
            <p className="landing-hero__copy">
              PasarConnect helps vendors list surplus food, gives charities
              priority access, and opens remaining items to public users through
              one clear flow.
            </p>

            <div className="landing-hero__actions">
              <a href="#role-selection" className="landing-button landing-button--primary">
                Choose Your Role
              </a>
              <a href="#how-it-works" className="landing-button landing-button--secondary">
                See How It Works
              </a>
            </div>
          </div>

          <div className="landing-hero__panel">
            {highlightCards.map((card) => (
              <div key={card.title} className="landing-highlight-card">
                <h2>{card.title}</h2>
                <p>{card.description}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="role-selection" className="landing-section landing-section--roles">
          <div className="landing-section__header">
            <p className="landing-eyebrow">Choose how you want to use PasarConnect</p>
            <h2>Start with the role that matches what you need to do.</h2>
            <p className="landing-section__copy">
              Each group uses the platform differently. Pick your main path
              first so you land in the right experience immediately.
            </p>
          </div>

          <div className="landing-role-grid">
            {roleCards.map((role) => (
              <Link
                key={role.title}
                to={role.to}
                className="landing-role-card"
                aria-label={role.cta}
              >
                <p className="landing-role-card__eyebrow">{role.eyebrow}</p>
                <div className="landing-role-card__header">
                  <h3>{role.title}</h3>
                  <span className="landing-role-card__arrow" aria-hidden="true">
                    →
                  </span>
                </div>
                <p>{role.description}</p>
                <span className="landing-role-card__cta">{role.cta}</span>
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
          <div className="landing-impact__content">
            <p className="landing-eyebrow landing-eyebrow--light">Why It Matters</p>
            <h2>Reducing food waste can also improve food access.</h2>
            <p>
              PasarConnect is designed to make redistribution practical and easy
              to follow. Vendors get a clearer outlet for surplus food, charities
              can respond faster, and public users can still access affordable food
              when listings remain unclaimed.
            </p>

            <div className="landing-impact__points">
              {impactPoints.map((point) => (
                <div key={point} className="landing-impact__point">
                  {point}
                </div>
              ))}
            </div>
          </div>
        </section>

        <footer className="landing-footer">
          <div className="landing-footer__brand">
            <p>PasarConnect</p>
            <span>
              A practical surplus-food redistribution platform for vendors,
              charities, and public users.
            </span>
          </div>
          <div className="landing-footer__links">
            <a href="/#home">Home</a>
            <a href="/#how-it-works">How It Works</a>
            <a href="/#impact">Impact</a>
            <Link to="/login">Login</Link>
          </div>
        </footer>
      </main>
    </div>
  );
}
