import { useEffect, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../lib/api";
import { useLive, useSession } from "../lib/session";

const LINKS = [
  { to: "/inbox", label: "Inbox" },
  { to: "/approvals", label: "Approvals", count: true },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/messages", label: "Messages" },
  { to: "/runs", label: "Agent runs" },
  { to: "/analytics", label: "Analytics" },
  { to: "/settings", label: "Settings" },
];

export function Layout({ children }: { children: ReactNode }) {
  const { me, logout, health } = useSession();
  const [pending, setPending] = useState(0);
  const refresh = async () => {
    const r = await api.GET("/api/runs", { params: { query: { status: "awaiting_approval" } } });
    if (r.data) setPending(r.data.length);
  };
  useEffect(() => {
    refresh();
  }, []);
  useLive((e) => {
    if (e.type === "run") refresh();
  });

  const nav = (
    <>
      {LINKS.map((l) => (
        <NavLink key={l.to} to={l.to} className={({ isActive }) => (isActive ? "active" : "")}>
          {l.label}
          {l.count && pending > 0 && (
            <span className="count" aria-label={`${pending} waiting`}>
              {pending}
            </span>
          )}
        </NavLink>
      ))}
    </>
  );

  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          Gig<span>Bid</span>
        </div>
        <nav className="nav">{nav}</nav>
        <div className="me">
          <div>{me?.name}</div>
          <button className="link small" onClick={logout}>
            Sign out
          </button>
        </div>
      </aside>
      <nav className="topbar" aria-label="Main navigation">
        {nav}
        <button className="link small" onClick={logout}>
          Sign out
        </button>
      </nav>
      <main id="main" className="main" tabIndex={-1}>
        {health && !health.marketplace_ok && (
          <div className="banner bad" role="alert" data-testid="degraded-banner">
            <div>
              <strong>Marketplace unavailable.</strong> GigBid can't reach {health.marketplace_mode === "upwork_live" ? "Upwork" : "GigSim"} right
              now. You can still review analysed jobs and drafts; new analyses and submissions are queued until it
              comes back. {health.marketplace_detail && <span className="small">({health.marketplace_detail})</span>}
            </div>
          </div>
        )}
        {health && !health.llm_available && (
          <div className="banner info small">
            <div>
              Running in <strong>rule mode</strong> (no model API key): drafts come from templates, and paragraph
              regeneration is off.
            </div>
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
