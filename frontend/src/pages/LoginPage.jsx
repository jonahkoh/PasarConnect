import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import TopNav from "../components/TopNav";

const roleOptions = [
  {
    id: "vendor",
    title: "Vendor",
    description:
      "Manage surplus listings and monitor which items move through the redistribution flow.",
    destination: "/vendor",
  },
  {
    id: "charity",
    title: "Charity",
    description:
      "Review available listings and claim food during the charity priority window.",
    destination: "/charity",
  },
  {
    id: "marketplace",
    title: "Public User",
    description:
      "Browse discounted surplus food that remains after the charity phase ends.",
    destination: "/marketplace",
  },
];

export default function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialRoleId = searchParams.get("role");
  const defaultRoleId = roleOptions.some((role) => role.id === initialRoleId)
    ? initialRoleId
    : roleOptions[0].id;
  const [selectedRoleId, setSelectedRoleId] = useState(defaultRoleId);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const selectedRole =
    roleOptions.find((role) => role.id === selectedRoleId) ?? roleOptions[0];

  function handleSubmit(event) {
    event.preventDefault();

    if (!email.trim() || !password.trim()) {
      return;
    }

    navigate(selectedRole.destination);
  }

  return (
    <div className="app-shell landing-shell">
      <TopNav />

      <main className="login-page">
        <section className="login-page__hero">
          <p className="landing-eyebrow">Login</p>
          <h1>Sign in and continue with the role that fits your task.</h1>
          <p className="login-page__copy">
            Vendors manage listings, charities claim priority items, and public
            users browse discounted food in the marketplace. Select your role
            first, then continue into the correct view.
          </p>
        </section>

        <section className="login-layout">
          <section className="login-panel">
            <div className="login-panel__header">
              <h2>Welcome back</h2>
              <p>Use the same account details and choose where you want to go.</p>
            </div>

            <form className="login-form" onSubmit={handleSubmit}>
              <div className="login-role-selector">
                {roleOptions.map((role) => (
                  <button
                    key={role.id}
                    type="button"
                    className={`login-role-selector__option${
                      selectedRoleId === role.id
                        ? " login-role-selector__option--active"
                        : ""
                    }`}
                    onClick={() => setSelectedRoleId(role.id)}
                    aria-pressed={selectedRoleId === role.id}
                  >
                    <span>{role.title}</span>
                  </button>
                ))}
              </div>

              <div className="login-role-summary" aria-live="polite">
                <p className="login-role-summary__label">Selected role</p>
                <strong>{selectedRole.title}</strong>
                <p>{selectedRole.description}</p>
              </div>

              <label className="login-form__field">
                <span>Email</span>
                <input
                  type="email"
                  placeholder="name@example.com"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </label>

              <label className="login-form__field">
                <span>Password</span>
                <input
                  type="password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>

              <div className="login-form__row">
                <label className="login-form__checkbox">
                  <input type="checkbox" />
                  <span>Remember me</span>
                </label>
                <Link to="/" className="login-form__help">
                  Back to landing page
                </Link>
              </div>

              <button type="submit" className="landing-button landing-button--primary">
                Continue to {selectedRole.title}
              </button>
            </form>
          </section>

          <aside className="login-role-panel">
            <div className="login-role-panel__header">
              <p className="landing-eyebrow">Where you will go</p>
              <h2>Each login path leads to its respective page.</h2>
            </div>

            <div className="login-role-grid">
              {roleOptions.map((role) => (
                <button
                  key={role.id}
                  type="button"
                  className={`login-role-card${
                    selectedRoleId === role.id ? " login-role-card--active" : ""
                  }`}
                  onClick={() => setSelectedRoleId(role.id)}
                >
                  <div className="login-role-card__header">
                    <h3>{role.title}</h3>
                    <span aria-hidden="true">→</span>
                  </div>
                  <p>{role.description}</p>
                </button>
              ))}
            </div>
          </aside>
        </section>
      </main>
    </div>
  );
}
