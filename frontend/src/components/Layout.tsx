import { Link, NavLink, Outlet } from "react-router-dom";
import { ActiveWorkflowBanner } from "./ActiveWorkflowBanner";
import { AuthPanel } from "./AuthPanel";

const navLinkClass = ({ isActive }: { isActive: boolean }) => (isActive ? "nav-link active" : "nav-link");

export function Layout() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <Link to="/">Meeting Assistant</Link>
          <p className="subtitle">Batch ingest, workflow status, search, and RAG query</p>
        </div>
        <nav className="nav">
          <NavLink to="/" end className={navLinkClass}>
            Upload
          </NavLink>
          <NavLink to="/workflow" className={navLinkClass}>
            Workflow
          </NavLink>
          <NavLink to="/search" className={navLinkClass}>
            Search
          </NavLink>
          <NavLink to="/query" className={navLinkClass}>
            Ask
          </NavLink>
          <NavLink to="/approvals" className={navLinkClass}>
            Approvals
          </NavLink>
          <NavLink to="/settings/integrations" className={navLinkClass}>
            Integrations
          </NavLink>
        </nav>
      </header>

      <aside className="sidebar">
        <AuthPanel />
        <ActiveWorkflowBanner />
      </aside>

      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
