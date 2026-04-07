import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import TopNav from "../components/TopNav";

const roleOptions = [
  { id: "public",  label: "Public User",  description: "Browse and purchase discounted surplus food." },
  { id: "charity", label: "Charity",       description: "Claim priority-window food for your organisation." },
  { id: "vendor",  label: "Vendor",        description: "List surplus food and manage your inventory." },
];

const REGISTER_PATHS = {
  public:  "/auth/public/register",
  charity: "/auth/charity/register",
  vendor:  "/auth/vendor/register",
};

export default function RegisterPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialRoleId = searchParams.get("role");
  const [roleId, setRoleId] = useState(
    roleOptions.some((r) => r.id === initialRoleId) ? initialRoleId : "public"
  );

  // Shared fields
  const [fullName,  setFullName]  = useState("");
  const [email,     setEmail]     = useState("");
  const [password,  setPassword]  = useState("");
  const [confirmPw, setConfirmPw] = useState("");

  // Public-only
  const [phone, setPhone] = useState("");

  // Charity-only
  const [orgName,    setOrgName]    = useState("");
  const [charityReg, setCharityReg] = useState("");

  // Vendor-only
  const [businessName,    setBusinessName]    = useState("");
  const [neaLicence,      setNeaLicence]      = useState("");
  const [licenceExpiry,   setLicenceExpiry]   = useState("");
  const [address,         setAddress]         = useState("");
  const [uen,             setUen]             = useState("");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error,        setError]        = useState("");
  const [successMsg,   setSuccessMsg]   = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSuccessMsg("");

    if (password !== confirmPw) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    let body = {};
    if (roleId === "public") {
      if (!fullName.trim() || !email.trim() || !phone.trim()) {
        setError("Please fill in all required fields.");
        return;
      }
      body = { FullName: fullName.trim(), Email: email.trim(), Password: password, Phone: phone.trim() };
    } else if (roleId === "charity") {
      if (!fullName.trim() || !email.trim() || !orgName.trim() || !charityReg.trim()) {
        setError("Please fill in all required fields.");
        return;
      }
      body = {
        FullName: fullName.trim(),
        Email: email.trim(),
        Password: password,
        OrgName: orgName.trim(),
        CharityRegNumber: charityReg.trim(),
      };
    } else {
      if (!fullName.trim() || !email.trim() || !businessName.trim() || !neaLicence.trim() || !licenceExpiry || !address.trim() || !uen.trim()) {
        setError("Please fill in all required fields.");
        return;
      }
      body = {
        FullName: fullName.trim(),
        Email: email.trim(),
        Password: password,
        BusinessName: businessName.trim(),
        NeaLicenceNumber: neaLicence.trim(),
        LicenceExpiry: licenceExpiry,
        Address: address.trim(),
        Uen: uen.trim(),
      };
    }

    setIsSubmitting(true);
    try {
      const res = await fetch(REGISTER_PATHS[roleId], {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const detail = typeof err.detail === "string" ? err.detail : null;
        if (res.status === 409) {
          setError("An account with this email already exists.");
        } else if (res.status === 422) {
          setError("Please check your details and try again.");
        } else {
          setError(detail ?? `Registration failed (${res.status}). Please try again.`);
        }
        return;
      }

      const data = await res.json().catch(() => ({}));
      const msg = data?.message ?? "Registration successful!";
      setSuccessMsg(msg);

      // Public users can log in immediately — redirect after a short pause.
      // Charity/vendor need admin approval — stay on the result screen.
      if (roleId === "public") {
        setTimeout(() => navigate(`/login?role=marketplace`), 2000);
      }
    } catch {
      setError("Could not reach the registration service. Check your connection and try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleRoleChange(id) {
    setRoleId(id);
    setError("");
    setSuccessMsg("");
  }

  return (
    <div className="app-shell landing-shell">
      <TopNav />

      <main className="login-page">
        <section className="login-page__hero">
          <p className="landing-eyebrow">Register</p>
          <h1>Create your PasarConnect account.</h1>
          <p className="login-page__copy">
            Select the role that best describes you and fill in the details below.
            Vendor and Charity accounts require admin approval before you can log in.
          </p>
        </section>

        <section className="login-layout register-layout">
          <section className="login-panel register-panel">
            <div className="login-panel__header">
              <h2>Create account</h2>
              <p>Already have one? <Link to="/login" className="register-inline-link">Sign in</Link></p>
            </div>

            {successMsg ? (
              <div className="register-success">
                <div className="register-success__icon">✓</div>
                <h3>{successMsg}</h3>
                {roleId !== "public" && (
                  <p>
                    Your account is pending admin approval. You will be notified
                    by email once it has been reviewed.
                  </p>
                )}
                {roleId === "public" && <p>Redirecting you to the login page…</p>}
                <Link to="/login" className="landing-button landing-button--primary register-success__btn">
                  Go to Login
                </Link>
              </div>
            ) : (
              <form className="login-form" onSubmit={handleSubmit}>
                {/* Role selector */}
                <div className="login-role-selector">
                  {roleOptions.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      className={`login-role-selector__option${roleId === r.id ? " login-role-selector__option--active" : ""}`}
                      onClick={() => handleRoleChange(r.id)}
                      aria-pressed={roleId === r.id}
                    >
                      <span>{r.label}</span>
                    </button>
                  ))}
                </div>

                <div className="login-role-summary" aria-live="polite">
                  <p className="login-role-summary__label">Registering as</p>
                  <strong>{roleOptions.find((r) => r.id === roleId)?.label}</strong>
                  <p>{roleOptions.find((r) => r.id === roleId)?.description}</p>
                  {(roleId === "charity" || roleId === "vendor") && (
                    <p className="register-approval-note">
                      ⏳ Requires admin approval before login is enabled.
                    </p>
                  )}
                </div>

                {/* Shared fields */}
                <label className="login-form__field">
                  <span>Full Name <span className="register-required">*</span></span>
                  <input
                    type="text"
                    placeholder="Your full name"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    required
                  />
                </label>

                <label className="login-form__field">
                  <span>Email <span className="register-required">*</span></span>
                  <input
                    type="email"
                    placeholder="name@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </label>

                <label className="login-form__field">
                  <span>Password <span className="register-required">*</span></span>
                  <input
                    type="password"
                    placeholder="At least 8 characters"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </label>

                <label className="login-form__field">
                  <span>Confirm Password <span className="register-required">*</span></span>
                  <input
                    type="password"
                    placeholder="Repeat your password"
                    value={confirmPw}
                    onChange={(e) => setConfirmPw(e.target.value)}
                    required
                  />
                </label>

                {/* Public-only */}
                {roleId === "public" && (
                  <label className="login-form__field">
                    <span>Phone Number <span className="register-required">*</span></span>
                    <input
                      type="tel"
                      placeholder="+65 9123 4567"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      required
                    />
                  </label>
                )}

                {/* Charity-only */}
                {roleId === "charity" && (
                  <>
                    <label className="login-form__field">
                      <span>Organisation Name <span className="register-required">*</span></span>
                      <input
                        type="text"
                        placeholder="e.g. Food from the Heart"
                        value={orgName}
                        onChange={(e) => setOrgName(e.target.value)}
                        required
                      />
                    </label>
                    <label className="login-form__field">
                      <span>Charity Registration Number <span className="register-required">*</span></span>
                      <input
                        type="text"
                        placeholder="e.g. 200012345A"
                        value={charityReg}
                        onChange={(e) => setCharityReg(e.target.value)}
                        required
                      />
                    </label>
                  </>
                )}

                {/* Vendor-only */}
                {roleId === "vendor" && (
                  <>
                    <label className="login-form__field">
                      <span>Business Name <span className="register-required">*</span></span>
                      <input
                        type="text"
                        placeholder="e.g. Sunrise Bakery"
                        value={businessName}
                        onChange={(e) => setBusinessName(e.target.value)}
                        required
                      />
                    </label>
                    <label className="login-form__field">
                      <span>NEA Licence Number <span className="register-required">*</span></span>
                      <input
                        type="text"
                        placeholder="e.g. NL-2024-12345"
                        value={neaLicence}
                        onChange={(e) => setNeaLicence(e.target.value)}
                        required
                      />
                    </label>
                    <label className="login-form__field">
                      <span>Licence Expiry Date <span className="register-required">*</span></span>
                      <input
                        type="date"
                        value={licenceExpiry}
                        onChange={(e) => setLicenceExpiry(e.target.value)}
                        required
                      />
                    </label>
                    <label className="login-form__field">
                      <span>Business Address <span className="register-required">*</span></span>
                      <input
                        type="text"
                        placeholder="e.g. 123 Orchard Road, #01-01"
                        value={address}
                        onChange={(e) => setAddress(e.target.value)}
                        required
                      />
                    </label>
                    <label className="login-form__field">
                      <span>UEN <span className="register-required">*</span></span>
                      <input
                        type="text"
                        placeholder="e.g. 202012345G"
                        value={uen}
                        onChange={(e) => setUen(e.target.value)}
                        required
                      />
                    </label>
                  </>
                )}

                <button
                  type="submit"
                  className="landing-button landing-button--primary"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? "Creating account…" : "Create Account"}
                </button>

                {error && <p className="login-form__error" role="alert">{error}</p>}

                <div className="register-footer-row">
                  <span>Already have an account?</span>
                  <Link to="/login" className="login-form__help">Sign in</Link>
                </div>
              </form>
            )}
          </section>
        </section>
      </main>
    </div>
  );
}
