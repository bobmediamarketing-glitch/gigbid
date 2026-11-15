import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Empty, ErrorBox, Fit, Loading, RiskBadge, StatusBadge, useData } from "../components/ui";
import { api, money, unwrap, type JobCard } from "../lib/api";
import { useLive, useSession } from "../lib/session";

const ACTION: Record<string, { label: string; tone: string }> = {
  bid: { label: "Bid", tone: "ok" },
  watch: { label: "Watch", tone: "info" },
  skip: { label: "Skip", tone: "" },
};

export default function Inbox() {
  const { me } = useSession();
  const [category, setCategory] = useState<string>("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const jobs = useData(
    async () => unwrap(await api.GET("/api/jobs", { params: { query: { category: category || undefined, q: query || undefined } } })),
    [category, query],
  );
  useLive((e) => {
    if (e.type === "run") jobs.reload();
  });

  async function act(fn: () => Promise<unknown>, key: string) {
    setBusy(key);
    setErr(null);
    try {
      await fn();
      jobs.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  }

  const cats = me?.settings.categories ?? [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Job inbox</h1>
          <p>Ranked by fit. Analysed jobs show a recommended action, risk, price and Connects cost.</p>
        </div>
        <button
          className="primary"
          onClick={() => act(async () => unwrap(await api.POST("/api/scout", { params: { query: { limit: 8 } } })), "scout")}
          disabled={busy === "scout"}
          data-testid="scout"
        >
          {busy === "scout" && <span className="spinner" />} Scout new jobs
        </button>
      </div>
      <div className="card tight row" role="search">
        <label htmlFor="cat" className="visually-hidden">Category</label>
        <select id="cat" value={category} onChange={(e) => setCategory(e.target.value)} style={{ maxWidth: 220 }}>
          <option value="">All categories</option>
          {cats.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        <label htmlFor="q" className="visually-hidden">Search</label>
        <input id="q" placeholder="Search words, e.g. langgraph" value={query} onChange={(e) => setQuery(e.target.value)} style={{ maxWidth: 320 }} />
        {jobs.data && <span className="muted small">{jobs.data.analysed} analysed of {jobs.data.items.length}</span>}
      </div>
      {err ? <ErrorBox error={err} /> : null}
      {jobs.error ? <ErrorBox error={jobs.error} retry={jobs.reload} /> : null}
      {jobs.loading && <Loading rows={5} label="Loading jobs" />}
      {jobs.data && jobs.data.items.length === 0 && (
        <Empty title="No jobs yet">
          <p>Try another category, or press <strong>Scout new jobs</strong>.</p>
        </Empty>
      )}
      {jobs.data?.items.map((j) => (
        <JobRow key={j.id} j={j} busy={busy} act={act} />
      ))}
    </>
  );
}

function JobRow({ j, busy, act }: { j: JobCard; busy: string | null; act: (fn: () => Promise<unknown>, key: string) => void }) {
  const r = j.run;
  const a = r?.action ? ACTION[r.action] : null;
  return (
    <article className="card job" data-testid={`job-${j.id}`}>
      <div>
        <Link className="job-title" to={`/jobs/${j.id}`}>
          {j.title}
        </Link>
        <div className="job-meta">
          <span>{j.category}</span>
          <span>·</span>
          <span>
            {money(j.budget.min, j.budget.type)}-{money(j.budget.max, j.budget.type)} {j.budget.type}
          </span>
          <span>·</span>
          <span>{j.connects_cost} Connects</span>
          {j.proposals_count !== null && j.proposals_count !== undefined && (
            <>
              <span>·</span>
              <span>{j.proposals_count} proposals</span>
            </>
          )}
        </div>
        <div className="row" style={{ marginTop: 6 }}>
          {a && <Badge tone={a.tone}>Recommended: {a.label}</Badge>}
          {r && <StatusBadge status={r.status} />}
          {r && <RiskBadge score={r.scam_score} type={r.scam_type} injection={r.injection} />}
          {r?.price && <Badge>Our price {money(r.price, r.bid_type)}</Badge>}
        </div>
        {r?.reasons?.[0] && <p className="small muted" style={{ marginTop: 6 }}>{r.reasons[0]}</p>}
      </div>
      <div>
        <Fit value={r?.coverage} />
        <div className="job-actions" style={{ marginTop: 8 }}>
          {!r && (
            <button
              onClick={() => act(async () => unwrap(await api.POST("/api/jobs/{job_id}/analyze", { params: { path: { job_id: j.id } } })), j.id)}
              disabled={busy === j.id}
            >
              {busy === j.id && <span className="spinner" />} Analyse
            </button>
          )}
          {r?.status === "running" && (
            <Link className="btn" to={`/runs/${r.thread_id}`}>
              <span className="spinner" /> Watch run
            </Link>
          )}
          {r?.pending && (
            <Link className="btn primary" to={`/studio/${r.thread_id}`}>
              Review proposal
            </Link>
          )}
          {r?.status === "skip_suggested" && (
            <button onClick={() => act(async () => unwrap(await api.POST("/api/jobs/{job_id}/skip", { params: { path: { job_id: j.id } } })), j.id)}>
              Confirm skip
            </button>
          )}
          <Link className="btn" to={`/jobs/${j.id}`}>
            Open
          </Link>
        </div>
      </div>
    </article>
  );
}
