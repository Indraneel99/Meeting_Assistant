import { useConfig } from "../context/ConfigContext";

export function UserSessionBar() {
  const { config, clearSession, authEnabled, isAuthenticated } = useConfig();

  if (!authEnabled) {
    return (
      <section className="panel compact">
        <h2>Session</h2>
        <p className="subtitle">{config.userExternalId}</p>
        <p>{config.userEmail}</p>
      </section>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <section className="panel compact">
      <h2>Signed in</h2>
      <p className="subtitle">{config.userEmail || config.userExternalId}</p>
      <button type="button" className="secondary" onClick={clearSession}>
        Sign out
      </button>
    </section>
  );
}
