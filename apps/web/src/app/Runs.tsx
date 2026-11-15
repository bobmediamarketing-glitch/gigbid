import { Link } from "react-router-dom";
import { Badge, Empty, ErrorBox, Loading, StatusBadge, useData } from "../components/ui";
import { ago, api, unwrap } from "../lib/client";
import { useLive } from "../lib/session";

export default function Runs() {
  const runs = useData(async () => unwrap(await api.GET("/api/runs")));
  useLive((e) => {
    if (e.type === "run") runs.reload();
  });
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Agent runs</h1>
          <p>Every bid and conversation thread, with its live progress and full history.</p>
        </div>
      </div>
      {runs.error ? <ErrorBox error={runs.error} retry={runs.reload} /> : null}
      {runs.loading && <Loading rows={4} />}
      {runs.data?.length === 0 && <Empty title="No runs yet">Analyse a job from the inbox to start one.</Empty>}
      {runs.data && runs.data.length > 0 && (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr><th>Run</th><th>Kind</th><th>Status</th><th>Steps / cost</th><th>Updated</th></tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <tr key={r.thread_id}>
                  <td><Link to={`/runs/${r.thread_id}`}>{r.title ?? r.market_thread_id ?? r.thread_id}</Link></td>
                  <td><Badge>{r.kind}</Badge></td>
                  <td><StatusBadge status={r.status} /></td>
                  <td className="small">{r.latency_ms ? `${(r.latency_ms / 1000).toFixed(1)} s` : "-"} · ${r.usd.toFixed(4)}</td>
                  <td className="small muted">{ago(r.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
