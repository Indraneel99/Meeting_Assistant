import { FormEvent, useEffect, useState } from "react";
import { checkHealth, getAuthConfig, login } from "../api/client";
import { useConfig } from "../context/ConfigContext";

export function AuthPanel() {
  const { config, updateConfig, clearSession, isAuthenticated } = useConfig();
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);
  const [loginAllowDev, setLoginAllowDev] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [userExternalId, setUserExternalId] = useState(config.userExternalId);
  const [userEmail, setUserEmail] = useState(config.userEmail);
  const [baseUrl, setBaseUrl] = useState(config.baseUrl);
  const [healthStatus, setHealthStatus] = useState<string | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getAuthConfig(baseUrl)
      .then((result) => {
        if (!cancelled) {
          setAuthEnabled(result.auth_enabled);
          setLoginAllowDev(result.login_allow_dev);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAuthEnabled(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [baseUrl]);

  async function handleHealthCheck() {
    setHealthStatus(null);
    setHealthError(null);
    try {
      const result = await checkHealth({ ...config, baseUrl });
      setHealthStatus(result.status);
    } catch (error) {
      setHealthError(error instanceof Error ? error.message : "Health check failed");
    }
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError(null);
    setBusy(true);
    try {
      const payload = authEnabled
        ? loginAllowDev
          ? {
              user_external_id: userExternalId,
              user_email: userEmail,
              ...(apiKey ? { api_key: apiKey } : {}),
            }
          : { api_key: apiKey, user_external_id: userExternalId, user_email: userEmail }
        : {
            user_external_id: userExternalId,
            user_email: userEmail,
          };

      if (authEnabled) {
        const session = await login(baseUrl, payload);
        updateConfig({
          baseUrl,
          accessToken: session.access_token,
          userExternalId: session.user_external_id,
          userEmail: session.user_email,
        });
      } else {
        updateConfig({
          baseUrl,
          accessToken: "",
          userExternalId: userExternalId,
          userEmail: userEmail,
        });
      }
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  function handleLogout() {
    clearSession();
    setApiKey("");
    setAuthError(null);
  }

  return (
    <section className="panel">
      <h2>{authEnabled ? "Sign in" : "Session"}</h2>
      {isAuthenticated ? (
        <div className="stack">
          <p className="success">Signed in as {config.userExternalId}</p>
          <p>{config.userEmail}</p>
          <div className="button-row">
            <button type="button" className="secondary" onClick={handleLogout}>
              Sign out
            </button>
            <button type="button" className="secondary" onClick={handleHealthCheck}>
              Check /health
            </button>
          </div>
        </div>
      ) : (
        <form className="stack" onSubmit={handleLogin}>
          <label>
            Base URL
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} required />
          </label>
          {authEnabled && !loginAllowDev && (
            <label>
              API key
              <input
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                type="password"
                required
                placeholder="Scoped key from Secret Manager"
              />
            </label>
          )}
          {authEnabled && loginAllowDev && (
            <label>
              API key (optional)
              <input
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                type="password"
                placeholder="Optional when dev login is enabled"
              />
            </label>
          )}
          {(loginAllowDev || !authEnabled) && (
            <>
              <label>
                User external ID
                <input
                  value={userExternalId}
                  onChange={(event) => setUserExternalId(event.target.value)}
                  required
                />
              </label>
              <label>
                User email
                <input
                  value={userEmail}
                  onChange={(event) => setUserEmail(event.target.value)}
                  type="email"
                  required
                />
              </label>
            </>
          )}
          {authEnabled && !loginAllowDev && (
            <>
              <label>
                User external ID
                <input
                  value={userExternalId}
                  onChange={(event) => setUserExternalId(event.target.value)}
                  placeholder="Required for unscoped admin keys"
                />
              </label>
              <label>
                User email
                <input
                  value={userEmail}
                  onChange={(event) => setUserEmail(event.target.value)}
                  type="email"
                />
              </label>
            </>
          )}
          <div className="button-row">
            <button type="submit" disabled={busy}>
              {authEnabled ? "Sign in" : "Save"}
            </button>
            <button type="button" className="secondary" onClick={handleHealthCheck}>
              Check /health
            </button>
          </div>
        </form>
      )}
      {healthStatus && <p className="success">API health: {healthStatus}</p>}
      {healthError && <p className="error">{healthError}</p>}
      {authError && <p className="error">{authError}</p>}
      {authEnabled === null && <p className="subtitle">Loading auth settings…</p>}
    </section>
  );
}
