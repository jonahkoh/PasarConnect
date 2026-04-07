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
  const [loginError, setLoginError] = useState("");

  const LOGIN_PATHS = {
    vendor:      "/auth/vendor/login",
    charity:     "/auth/charity/login",
    marketplace: "/auth/public/login",
  };

  const selectedRole =
    roleOptions.find((role) => role.id === selectedRoleId) ?? roleOptions[0];

  async function handleSubmit(event) {
    event.preventDefault();
    if (!email.trim() || !password.trim()) return;

    setLoginError("");
    // Clear any stale session before a new login attempt.
    sessionStorage.removeItem("authToken");
    sessionStorage.removeItem("authRole");
    sessionStorage.removeItem("authUserId");

    try {
      const response = await fetch(LOGIN_PATHS[selectedRoleId], {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ email: email.trim(), password: password.trim() }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        const detail = typeof err.detail === "string" ? err.detail : null;

        if (response.status === 401) {
          setLoginError("Incorrect email or password. Please try again.");
        } else if (response.status === 403 && detail?.toLowerCase().includes("pending approval")) {
          setLoginError("Your account is pending admin approval. You'll be notified when it's activated.");
        } else if (response.status === 403) {
          setLoginError(detail ?? "You don't have access to this role. Please select the correct role.");
        } else if (response.status === 503) {
          setLoginError("Login service is temporarily unavailable. Please try again shortly.");
        } else {
          setLoginError(detail ?? `Login failed (${response.status}). Please try again.`);
        }
        return;
      }

      const data = await response.json();
      sessionStorage.setItem("authToken",  data.access_token);
      sessionStorage.setItem("authRole",   data.role);
      sessionStorage.setItem("authUserId", String(data.user_id));
      // Store email as a friendly display name for the TopNav.
      sessionStorage.setItem("authUserName", email.trim());
      // Full page navigation so App remounts and re-reads authUser from sessionStorage.
      window.location.href = selectedRole.destination;
    } catch {
      setLoginError("Could not reach the login service. Check your connection and try again.");
    }
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
          <section className="login-panel" style={{ maxWidth: 480, margin: "0 auto" }}>
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
                <Link to="/register" className="login-form__help">
                  Create an account
                </Link>
              </div>

              <button type="submit" className="landing-button landing-button--primary">
                Continue to {selectedRole.title}
              </button>

              {loginError && (
                <p className="login-form__error" role="alert">{loginError}</p>
              )}
            </form>
          </section>

        </section>
      </main>
    </div>
  );
}
