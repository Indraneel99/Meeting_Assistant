import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { getGoogleConnectUrl, loginEmail } from "../api/client";
import { useConfig } from "../context/ConfigContext";

function parseOAuthFragment(): Record<string, string> {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  if (!hash) {
    return {};
  }
  return Object.fromEntries(new URLSearchParams(hash));
}

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { config, updateConfig, authEnabled, passwordLoginEnabled, googleLoginEnabled, isAuthenticated } = useConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = parseOAuthFragment();
    const accessToken = params.access_token;
    if (!accessToken) {
      return;
    }

    updateConfig({
      accessToken,
      userExternalId: params.user_external_id || config.userExternalId,
    });
    window.history.replaceState({}, document.title, window.location.pathname);
    navigate((location.state as { from?: string } | null)?.from || "/", { replace: true });
  }, [config.userExternalId, location.state, navigate, updateConfig]);

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
      const session = await loginEmail(config.baseUrl, { email, password });
      updateConfig({
        accessToken: session.access_token,
        userExternalId: session.user_external_id,
        userEmail: session.user_email,
      });
      navigate((location.state as { from?: string } | null)?.from || "/", { replace: true });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleGoogleSignIn() {
    setError(null);
    setBusy(true);
    try {
      const frontendRedirect = `${window.location.origin}/login`;
      const authorizeUrl = await getGoogleConnectUrl(config.baseUrl, frontendRedirect);
      window.location.href = authorizeUrl;
    } catch (googleError) {
      setError(googleError instanceof Error ? googleError.message : "Google sign-in failed");
      setBusy(false);
    }
  }

  if (!authEnabled) {
    return (
      <div className="auth-page">
        <section className="panel auth-card">
          <h1>Sign in not required</h1>
          <p className="subtitle">Authentication is disabled on this API.</p>
          <Link to="/" className="text-link">
            Continue to app
          </Link>
        </section>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <section className="panel auth-card">
        <h1>Sign in</h1>
        <p className="subtitle">Use your Meeting Assistant account.</p>

        {passwordLoginEnabled && (
          <form className="stack" onSubmit={handleSubmit}>
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
                autoComplete="current-password"
                required
              />
            </label>
            <button type="submit" disabled={busy}>
              Sign in
            </button>
          </form>
        )}

        {googleLoginEnabled && (
          <div className="stack">
            {passwordLoginEnabled && <p className="subtitle auth-divider">or</p>}
            <button type="button" className="secondary" disabled={busy} onClick={handleGoogleSignIn}>
              Sign in with Google
            </button>
          </div>
        )}

        {passwordLoginEnabled && (
          <p className="subtitle">
            No account? <Link to="/register">Create one</Link>
          </p>
        )}

        {error && <p className="error">{error}</p>}
      </section>
    </div>
  );
}
