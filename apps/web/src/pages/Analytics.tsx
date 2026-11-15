import { Empty, ErrorBox, Loading, useData } from "../components/ui";
import { api, pct, unwrap } from "../lib/api";

export default function Analytics() {
  const a = useData(async () => unwrap(await api.GET("/api/analytics")));
  if (a.loading) return <Loading rows={3} />;
  if (a.error) return <ErrorBox error={a.error} retry={a.reload} />;
  const d = a.data!;
  const maxCat = Math.max(1, ...d.by_category.map((c) => c.proposals));
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Analytics</h1>
          <p>How your proposals are doing, what they cost, and why jobs were skipped or rejected.</p>
        </div>
      </div>
      <div className="grid-3">
        <div className="card"><div className="muted small">Proposals sent</div><div className="stat">{d.proposals}</div></div>
        <div className="card"><div className="muted small">Reply rate</div><div className="stat">{pct(d.reply_rate)}</div><div className="small muted">hire rate {pct(d.hire_rate)}</div></div>
        <div className="card"><div className="muted small">Connects spent</div><div className="stat">{d.connects_spent}</div><div className="small muted">{d.connects_on_replied} on proposals that got replies</div></div>
      </div>
      <div className="grid-3">
        <div className="card"><div className="muted small">Model cost per proposal</div><div className="stat">${d.avg_usd_per_proposal.toFixed(4)}</div></div>
        <div className="card"><div className="muted small">Agent time per proposal</div><div className="stat">{d.avg_latency_s.toFixed(1)} s</div></div>
        <div className="card"><div className="muted small">Categories</div><div className="stat">{d.by_category.length}</div></div>
      </div>
      {d.proposals === 0 ? (
        <Empty title="No proposals yet">Numbers appear once you've approved a few proposals.</Empty>
      ) : (
        <section className="card" aria-labelledby="h-cat">
          <h2 id="h-cat">By category</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Category</th><th>Proposals</th><th>Reply rate</th><th>Hire rate</th><th>Connects</th></tr></thead>
              <tbody>
                {d.by_category.map((c) => (
                  <tr key={c.category}>
                    <td>{c.category}<div className="bar" style={{ width: `${(c.proposals / maxCat) * 100}%`, marginTop: 4 }} aria-hidden /></td>
                    <td>{c.proposals}</td><td>{pct(c.reply_rate)}</td><td>{pct(c.hire_rate)}</td><td>{c.connects}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <div className="grid-2">
        <section className="card" aria-labelledby="h-rej">
          <h2 id="h-rej">Why you rejected drafts</h2>
          {d.rejection_reasons.length === 0 ? <p className="muted small">No rejections yet.</p> : (
            <ul>{d.rejection_reasons.map((r) => <li key={String(r.reason)}>{String(r.reason)} <span className="muted">×{String(r.count)}</span></li>)}</ul>
          )}
        </section>
        <section className="card" aria-labelledby="h-skip">
          <h2 id="h-skip">Why jobs were skipped</h2>
          {d.skip_reasons.length === 0 ? <p className="muted small">No skips yet.</p> : (
            <ul>{d.skip_reasons.map((r) => <li key={String(r.reason)}>{String(r.reason)} <span className="muted">×{String(r.count)}</span></li>)}</ul>
          )}
        </section>
      </div>
    </>
  );
}
