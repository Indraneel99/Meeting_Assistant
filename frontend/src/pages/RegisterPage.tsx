import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { registerAccount } from "../api/client";
import { useConfig } from "../context/ConfigContext";

export function RegisterPage() {
  const navigate = useNavigate();
  const { config, updateConfig, authEnabled, passwordLoginEnabled, isAuthenticated } = useConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isAuthenticated) {
      navigate("/", { replace: true });
    }
  }, [isAuthenticated, navigate]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const session = await registerAccount(config.baseUrl, {
        email,
        password,
        display_name: displayName || undefined,
      });
      updateConfig({
        accessToken: session.access_token,
        userExternalId: session.user_external_id,
        userEmail: session.user_email,
      });
      navigate("/", { replace: true });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  if (!authEnabled || !passwordLoginEnabled) {
    return (
      <div className="auth-page">
        <section className="panel auth-card">
          <h1>Registration unavailable</h1>
          <p className="subtitle">Email and password registration is disabled.</p>
          <Link to="/login" className="text-link">
            Back to sign in
          </Link>
        </section>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <section className="panel auth-card">
        <h1>Create account</h1>
        <p className="subtitle">Register with email and password.</p>

        <form className="stack" onSubmit={handleSubmit}>
          <label>
            Display name
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              autoComplete="name"
              placeholder="Optional"
            />
          </label>
          <label>
            Email
            <input
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              type="email"
              autoComplete="email"
              required
            />
          </label>
          <label>
            Password
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
            />
          </label>
          <button type="submit" disabled={busy}>
            Create account
          </button>
        </form>

        <p className="subtitle">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>

        {error && <p className="error">{error}</p>}
      </section>
    </div>
  );
}
