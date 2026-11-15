import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorBox, Loading, useData } from "../components/ui";
import { api, unwrap } from "../lib/api";
import { useSession } from "../lib/session";

const STEPS = ["Profile", "Marketplace", "Rates & filters", "Portfolio"];

export default function Onboarding() {
  const { refresh } = useSession();
  const nav = useNavigate();
  const personas = useData(async () => unwrap(await api.GET("/api/personas")));
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<"persona" | "own">("persona");
  const [persona, setPersona] = useState<string>("");
  const [own, setOwn] = useState({ name: "", title: "", skills: "", categories: "" });
  const [market, setMarket] = useState<"gigsim" | "upwork_live">("gigsim");
  const [hourly, setHourly] = useState<string>("");
  const [fixed, setFixed] = useState<string>("");
  const [cats, setCats] = useState<string[]>([]);
  const [budget, setBudget] = useState("60");
  const [files, setFiles] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const chosen = personas.data?.find((p) => p.id === persona);
  const allCats = chosen?.categories ?? own.categories.split(",").map((c) => c.trim()).filter(Boolean);

  async function save(finish = false) {
    setBusy(true);
    setError(null);
    try {
      unwrap(
        await api.PUT("/api/settings", {
          body: {
            profile_mode: mode,
            persona: mode === "persona" ? persona : null,
            own_profile:
              mode === "own"
                ? {
                    name: own.name,
                    title: own.title,
                    skills: own.skills.split(",").map((s) => s.trim()).filter(Boolean),
                    categories: own.categories.split(",").map((s) => s.trim()).filter(Boolean),
                  }
                : null,
            marketplace: market,
            gigsim_account: mode === "persona" ? persona : "ai_ml",
            hourly_floor: hourly ? Number(hourly) : chosen?.hourly_floor ?? null,
            fixed_floor: fixed ? Number(fixed) : chosen?.fixed_floor ?? null,
            categories: cats.length ? cats : allCats,
            weekly_connects_budget: Number(budget) || 60,
            ...(finish ? { onboarded: true } : {}),
          },
        }),
      );
      if (finish) {
        await refresh();
        nav("/inbox");
      }
    } catch (e) {
      setError(e);
      throw e;
    } finally {
      setBusy(false);
    }
  }

  async function next() {
    if (step === 0 && mode === "persona" && !persona) return setError(new Error("Choose a persona to continue."));
    if (step === 0 && mode === "own" && (!own.name || !own.title)) return setError(new Error("Add your name and title."));
    setError(null);
    if (step === 2 && mode === "own") await save(false); // creates the portfolio folder before uploads
    if (step === STEPS.length - 1 || (step === 2 && mode === "persona")) return save(true);
    setStep(step + 1);
  }

  async function upload(kind: string, file: File) {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`/api/portfolio/files?kind=${kind}`, { method: "POST", body: fd, credentials: "same-origin" });
    if (!r.ok) return setError(new Error((await r.json()).detail ?? "upload failed"));
    const j = await r.json();
    setFiles((f) => [...f, j.path]);
  }

  return (
    <div style={{ maxWidth: 760, margin: "4vh auto", padding: "0 16px" }}>
      <h1>Set up GigBid</h1>
      <ol className="row small muted" aria-label="Steps" style={{ listStyle: "none", padding: 0 }}>
        {STEPS.map((s, i) => (
          <li key={s} aria-current={i === step ? "step" : undefined} style={{ fontWeight: i === step ? 700 : 400, color: i === step ? "var(--accent)" : undefined }}>
            {i + 1}. {s}
          </li>
        ))}
      </ol>
      {error ? <ErrorBox error={error} /> : null}
      <div className="card">
        {step === 0 && (
          <fieldset>
            <legend>Who are you bidding as?</legend>
            <label className={`choice ${mode === "persona" ? "selected" : ""}`}>
              <input type="radio" name="mode" checked={mode === "persona"} onChange={() => setMode("persona")} />
              <span><strong>Use a demo persona</strong><br /><span className="muted small">A ready-made portfolio (CV, case studies, repos, reviews, past proposals) and a GigSim account.</span></span>
            </label>
            <label className={`choice ${mode === "own" ? "selected" : ""}`}>
              <input type="radio" name="mode" checked={mode === "own"} onChange={() => setMode("own")} />
              <span><strong>Use my own profile</strong><br /><span className="muted small">Upload your own CV and case studies in the last step.</span></span>
            </label>
            {mode === "persona" &&
              (personas.loading ? (
                <Loading rows={2} />
              ) : (
                <div role="radiogroup" aria-label="Persona" style={{ marginTop: 12 }}>
                  {personas.data?.map((p) => (
                    <label key={p.id} className={`choice ${persona === p.id ? "selected" : ""}`} data-testid={`persona-${p.id}`}>
                      <input type="radio" name="persona" value={p.id} checked={persona === p.id} onChange={() => setPersona(p.id)} />
                      <span>
                        <strong>{p.name}</strong>, {p.title}
                        <br />
                        <span className="muted small">{p.skills.slice(0, 8).join(", ")}</span>
                      </span>
                    </label>
                  ))}
                </div>
              ))}
            {mode === "own" && (
              <div>
                <label htmlFor="own-name">Your name</label>
                <input id="own-name" value={own.name} onChange={(e) => setOwn({ ...own, name: e.target.value })} />
                <label htmlFor="own-title">Headline</label>
                <input id="own-title" value={own.title} onChange={(e) => setOwn({ ...own, title: e.target.value })} placeholder="Data engineer: dbt, Snowflake, Airflow" />
                <label htmlFor="own-skills">Skills <span className="field-hint">(comma separated)</span></label>
                <input id="own-skills" value={own.skills} onChange={(e) => setOwn({ ...own, skills: e.target.value })} />
                <label htmlFor="own-cats">Job categories you take <span className="field-hint">(comma separated)</span></label>
                <input id="own-cats" value={own.categories} onChange={(e) => setOwn({ ...own, categories: e.target.value })} />
              </div>
            )}
          </fieldset>
        )}

        {step === 1 && (
          <fieldset>
            <legend>Connect a marketplace</legend>
            <label className={`choice ${market === "gigsim" ? "selected" : ""}`}>
              <input type="radio" name="market" checked={market === "gigsim"} onChange={() => setMarket("gigsim")} />
              <span><strong>GigSim</strong> (simulator)<br /><span className="muted small">Realistic jobs and simulated clients who reply, negotiate and hire. Safe to experiment.</span></span>
            </label>
            <label className={`choice ${market === "upwork_live" ? "selected" : ""}`}>
              <input type="radio" name="market" checked={market === "upwork_live"} onChange={() => setMarket("upwork_live")} />
              <span>
                <strong>Upwork</strong> (live, read-mostly)<br />
                <span className="muted small">Reads jobs through Upwork's official MCP server. Proposals are created as drafts you confirm on Upwork; nothing is sent automatically. You'll connect with OAuth in Settings.</span>
              </span>
            </label>
          </fieldset>
        )}

        {step === 2 && (
          <fieldset>
            <legend>Rates, filters and budget</legend>
            <div className="grid-3">
              <div>
                <label htmlFor="hourly">Hourly floor ($)</label>
                <input id="hourly" type="number" min={0} value={hourly} placeholder={String(chosen?.hourly_floor ?? 30)} onChange={(e) => setHourly(e.target.value)} />
              </div>
              <div>
                <label htmlFor="fixed">Fixed-price floor ($)</label>
                <input id="fixed" type="number" min={0} value={fixed} placeholder={String(chosen?.fixed_floor ?? 300)} onChange={(e) => setFixed(e.target.value)} />
              </div>
              <div>
                <label htmlFor="budget">Weekly Connects budget</label>
                <input id="budget" type="number" min={0} value={budget} onChange={(e) => setBudget(e.target.value)} />
              </div>
            </div>
            <label>Categories to scout</label>
            <div className="row">
              {allCats.map((c) => (
                <label key={c} className="choice" style={{ marginBottom: 0 }}>
                  <input type="checkbox" checked={cats.length === 0 || cats.includes(c)} onChange={(e) => {
                    const base = cats.length === 0 ? allCats : cats;
                    setCats(e.target.checked ? [...new Set([...base, c])] : base.filter((x) => x !== c));
                  }} />
                  {c}
                </label>
              ))}
            </div>
          </fieldset>
        )}

        {step === 3 && (
          <fieldset>
            <legend>Upload your portfolio</legend>
            <p className="muted small">GigBid only claims what these files prove. New files are indexed as soon as they land.</p>
            {[["cv", "CV (PDF)", ".pdf"], ["case_study", "Case study (Markdown)", ".md"], ["repo_readme", "Repo README (Markdown)", ".md"], ["reviews", "Client reviews (JSON)", ".json"], ["past_proposals", "Past proposals (JSONL)", ".jsonl"]].map(([k, label, accept]) => (
              <div key={k}>
                <label htmlFor={`up-${k}`}>{label}</label>
                <input id={`up-${k}`} type="file" accept={accept} onChange={(e) => e.target.files?.[0] && upload(k, e.target.files[0])} />
              </div>
            ))}
            {files.length > 0 && <p className="small">Uploaded: {files.join(", ")}</p>}
          </fieldset>
        )}

        <div className="row" style={{ justifyContent: "space-between", marginTop: 8 }}>
          <button onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0 || busy}>
            Back
          </button>
          <button className="primary" onClick={next} disabled={busy} data-testid="onboarding-next">
            {busy && <span className="spinner" />}
            {step === STEPS.length - 1 || (step === 2 && mode === "persona") ? "Finish setup" : "Continue"}
          </button>
        </div>
      </div>
    </div>
  );
}
