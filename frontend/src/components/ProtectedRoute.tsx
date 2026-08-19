import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useConfig } from "../context/ConfigContext";

export function ProtectedRoute() {
  const { authEnabled, isAuthenticated, authLoading } = useConfig();
  const location = useLocation();

  if (authLoading) {
    return (
      <div className="auth-page">
        <section className="panel auth-card">
          <p className="subtitle">Loading…</p>
        </section>
      </div>
    );
  }

  if (authEnabled && !isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}
