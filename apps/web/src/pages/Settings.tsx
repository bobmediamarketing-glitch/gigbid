import { useState } from "react";
import { Badge, ErrorBox, Loading, useData } from "../components/ui";
import { api, pct, unwrap, type Settings as SettingsT } from "../lib/api";
import { useSession } from "../lib/session";

export default function Settings() {
  const { refresh } = useSession();
  const s = useData(async () => unwrap(await api.GET("/api/settings")));
  const mem = useData(async () => unwrap(await api.GET("/api/memory")));
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [search, setSearch] = useState({ name: "", category: "", query: "", interval_min: 60 });

  async function save(patch: Partial<SettingsT>) {
    setErr(null);
    try {
      const r = unwrap(await api.PUT("/api/settings", { body: patch as any }));
      s.setData(r);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      refresh();
    } catch (e) {
      setErr(e);
    }
  }
  async function forget(key: string) {
    await api.DELETE("/api/memory/style/{key}", { params: { path: { key } } });
    mem.reload();
  }
  async function forgetOutcome(category: string) {
    await api.DELETE("/api/memory/outcome/{category}", { params: { path: { category } } });
    mem.reload();
  }

  if (s.loading) return <Loading rows={4} />;
  if (s.error) return <ErrorBox error={s.error} retry={s.reload} />;
  const v = s.data!;
  const searches = v.saved_searches ?? [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Autonomy, budgets, searches, connected accounts, and what GigBid has learned about you.</p>
        </div>
        {saved && <Badge tone="ok">Saved</Badge>}
      </div>
      {err ? <ErrorBox error={err} /> : null}
      <div className="grid-2">
        <div>
          <section className="card" aria-labelledby="h-auto">
            <h2 id="h-auto">Autonomy</h2>
            <label className={`choice ${v.autonomy === "suggest" ? "selected" : ""}`}>
              <input type="radio" name="autonomy" checked={v.autonomy === "suggest"} onChange={() => save({ autonomy: "suggest" })} />
              <span><strong>Suggest</strong><br /><span className="small muted">Low-fit jobs wait in the inbox as "skip suggested" until you confirm.</span></span>
            </label>
            <label className={`choice ${v.autonomy === "auto_skip" ? "selected" : ""}`}>
              <input type="radio" name="autonomy" checked={v.autonomy === "auto_skip"} onChange={() => save({ autonomy: "auto_skip" })} data-testid="autonomy-auto" />
              <span><strong>Auto-skip low-fit jobs</strong><br /><span className="small muted">Clear mismatches close themselves. Proposals and messages are still never sent without you.</span></span>
            </label>
          </section>

          <section className="card" aria-labelledby="h-budget">
            <h2 id="h-budget">Budgets and rates</h2>
            <div className="grid-3">
              <div><label htmlFor="wcb">Weekly Connects</label><input id="wcb" type="number" defaultValue={v.weekly_connects_budget} onBlur={(e) => save({ weekly_connects_budget: Number(e.target.value) })} /></div>
              <div><label htmlFor="hf">Hourly floor</label><input id="hf" type="number" defaultValue={v.hourly_floor ?? ""} onBlur={(e) => save({ hourly_floor: Number(e.target.value) || null })} /></div>
              <div><label htmlFor="ff">Fixed floor</label><input id="ff" type="number" defaultValue={v.fixed_floor ?? ""} onBlur={(e) => save({ fixed_floor: Number(e.target.value) || null })} /></div>
            </div>
            <p className="small muted">Per-run step and token budgets are set by the operator in agent/config.yaml; a run that hits one moves to "needs attention".</p>
          </section>

          <section className="card" aria-labelledby="h-search">
            <h2 id="h-search">Saved searches</h2>
            {searches.length === 0 && <p className="small muted">None yet. The worker scouts each saved search on its schedule.</p>}
            <ul>
              {searches.map((x, i) => (
                <li key={i}>
                  <strong>{x.name}</strong> <span className="small muted">{x.category ?? "any category"} {x.query ? `· "${x.query}"` : ""} · every {x.interval_min} min</span>{" "}
                  <button className="link small" onClick={() => save({ saved_searches: searches.filter((_, j) => j !== i) })}>remove</button>
                </li>
              ))}
            </ul>
            <form className="grid-3" onSubmit={(e) => { e.preventDefault(); if (search.name) save({ saved_searches: [...searches, { ...search, category: search.category || null, query: search.query || null }] }); setSearch({ name: "", category: "", query: "", interval_min: 60 }); }}>
              <div><label htmlFor="ss-name">Name</label><input id="ss-name" value={search.name} onChange={(e) => setSearch({ ...search, name: e.target.value })} /></div>
              <div><label htmlFor="ss-cat">Category</label><input id="ss-cat" value={search.category} onChange={(e) => setSearch({ ...search, category: e.target.value })} /></div>
              <div><label htmlFor="ss-int">Every (min)</label><input id="ss-int" type="number" min={15} value={search.interval_min} onChange={(e) => setSearch({ ...search, interval_min: Number(e.target.value) })} /></div>
              <div><button type="submit">Add search</button></div>
            </form>
          </section>

          <section className="card" aria-labelledby="h-acc">
            <h2 id="h-acc">Connected accounts</h2>
            <p>GigSim: <Badge tone={v.marketplace === "gigsim" ? "ok" : ""}>{v.marketplace === "gigsim" ? `active (${v.gigsim_account})` : "available"}</Badge></p>
            <p>
              Upwork: {v.upwork_connected ? <Badge tone="ok">connected</Badge> : <Badge>not connected</Badge>}{" "}
              <a className="btn" href="/api/auth/upwork/start">Connect with OAuth</a>
            </p>
            <p className="small muted">Upwork tokens are stored encrypted and used only through Upwork's official MCP server. Live proposals are drafts you confirm on Upwork.</p>
            <label htmlFor="mk">Active marketplace</label>
            <select id="mk" value={v.marketplace} onChange={(e) => save({ marketplace: e.target.value as SettingsT["marketplace"] })}>
              <option value="gigsim">GigSim (simulator)</option>
              <option value="upwork_live" disabled={!v.upwork_connected}>Upwork (live){v.upwork_connected ? "" : " (connect first)"}</option>
            </select>
          </section>
        </div>

        <section className="card" aria-labelledby="h-mem" data-testid="memory">
          <h2 id="h-mem">What GigBid has learned</h2>
          <p className="small muted">Only promoted knowledge is kept. Style rules come from patterns repeated across your edits; outcome lessons need several results in a category. Delete anything you disagree with.</p>
          {mem.loading && <Loading rows={2} />}
          <h3>Style rules</h3>
          {mem.data?.style.length === 0 && <p className="small muted">None yet.</p>}
          {mem.data?.style.map((r) => (
            <div key={r.key} className="note ok row" style={{ justifyContent: "space-between" }}>
              <span><strong>{r.value}</strong> <span className="small muted">({r.kind.replace("_", " ")}, seen in {r.count} edits)</span></span>
              <button className="link small" onClick={() => forget(r.key)} aria-label={`Delete rule ${r.value}`}>Delete</button>
            </div>
          ))}
          {mem.data && mem.data.style_pending.length > 0 && (
            <>
              <h3 style={{ marginTop: 12 }}>Seen once (not a rule yet)</h3>
              {mem.data.style_pending.map((r) => (
                <div key={r.key} className="note small row" style={{ justifyContent: "space-between" }}>
                  <span>{r.value} <span className="muted">({r.kind.replace("_", " ")})</span></span>
                  <button className="link small" onClick={() => forget(r.key)}>Forget</button>
                </div>
              ))}
            </>
          )}
          <h3 style={{ marginTop: 12 }}>Outcome lessons</h3>
          {mem.data?.outcome.length === 0 && <p className="small muted">None yet: needs at least 5 resolved proposals in a category.</p>}
          {mem.data?.outcome.map((o) => (
            <div key={o.category} className="note">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>{o.category}</strong>
                <button className="link small" onClick={() => forgetOutcome(o.category)}>Delete</button>
              </div>
              <div className="small muted">{o.n} proposals · reply rate {pct(o.reply_rate)} · {o.won} hired</div>
              <ul className="small">{o.lessons.map((l: any, i: number) => <li key={i}>{String(l.feature).replace("_", " ")} = {String(l.value)}: {pct(Number(l.reply_rate))} replies (n={String(l.n)})</li>)}</ul>
            </div>
          ))}
        </section>
      </div>
    </>
  );
}
