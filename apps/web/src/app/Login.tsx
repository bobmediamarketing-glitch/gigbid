import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api, unwrap } from "../lib/client";
import { useSession } from "../lib/session";

export default function Login() {
  const { me, refresh } = useSession();
  const nav = useNavigate();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me) return <Navigate to={me.settings.onboarded ? "/inbox" : "/onboarding"} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") unwrap(await api.POST("/api/auth/register", { body: { email, password, name } }));
      else unwrap(await api.POST("/api/auth/login", { body: { email, password } }));
      await refresh();
      nav("/inbox");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 420, margin: "8vh auto", padding: "0 16px" }}>
      <div className="brand" style={{ fontSize: "1.6rem", padding: 0, marginBottom: 6 }}>
        Gig<span style={{ color: "var(--accent)" }}>Bid</span>
      </div>
      <p className="muted">Your freelancing copilot. It finds jobs that fit, proves your fit with your own work, and never sends anything without your approval.</p>
      <form className="card" onSubmit={submit} aria-labelledby="auth-title">
        <h1 id="auth-title">{mode === "signin" ? "Sign in" : "Create your account"}</h1>
        {error && (
          <div className="banner bad" role="alert">
            {error}
          </div>
        )}
        {mode === "signup" && (
          <>
            <label htmlFor="name">Name</label>
            <input id="name" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
          </>
        )}
        <label htmlFor="email">Email</label>
        <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        <label htmlFor="password">
          Password {mode === "signup" && <span className="field-hint">(8+ characters)</span>}
        </label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={mode === "signup" ? 8 : 1}
          autoComplete={mode === "signup" ? "new-password" : "current-password"}
        />
        <div className="row" style={{ marginTop: 16, justifyContent: "space-between" }}>
          <button className="primary" type="submit" disabled={busy}>
            {busy && <span className="spinner" />} {mode === "signin" ? "Sign in" : "Create account"}
          </button>
          <button type="button" className="link" onClick={() => setMode(mode === "signin" ? "signup" : "signin")}>
            {mode === "signin" ? "New here? Create an account" : "Have an account? Sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}
