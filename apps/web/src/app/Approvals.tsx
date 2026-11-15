import { Link } from "react-router-dom";
import { Badge, Empty, ErrorBox, Loading, useData } from "../components/ui";
import { ago, api, money, unwrap } from "../lib/client";
import { useLive } from "../lib/session";

export default function Approvals() {
  const runs = useData(async () => unwrap(await api.GET("/api/runs", { params: { query: { status: "awaiting_approval" } } })));
  useLive((e) => {
    if (e.type === "run") runs.reload();
  });
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Waiting for your approval</h1>
          <p>Nothing is sent, submitted or spent until you approve it here. Pending approvals survive page refreshes and restarts.</p>
        </div>
      </div>
      {runs.error ? <ErrorBox error={runs.error} retry={runs.reload} /> : null}
      {runs.loading && <Loading rows={3} />}
      {runs.data?.length === 0 && <Empty title="All clear">No proposals or replies are waiting.</Empty>}
      {runs.data?.map((r) => (
        <article className="card job" key={r.thread_id} data-testid={`approval-${r.thread_id}`}>
          <div>
            <Link className="job-title" to={r.kind === "bid" ? `/studio/${r.thread_id}` : `/messages?thread=${r.market_thread_id}`}>
              {r.kind === "bid" ? r.title : `Reply in ${r.market_thread_id}`}
            </Link>
            <div className="job-meta">
              <Badge tone="info">{r.kind === "bid" ? "Proposal" : `Reply · ${r.intent ?? ""}`}</Badge>
              {r.price && <span>{money(r.price, r.bid_type)}</span>}
              {r.connects_cost && <span>{r.connects_cost} Connects</span>}
              {r.critic !== null && r.critic !== undefined && <span>Critic {Math.round(r.critic * 100)}/100</span>}
              <span>{ago(r.updated_at)}</span>
            </div>
            {r.client_message && <p className="small muted">Client: "{r.client_message}"</p>}
          </div>
          <Link className="btn primary" to={r.kind === "bid" ? `/studio/${r.thread_id}` : `/messages?thread=${r.market_thread_id}`}>
            Review
          </Link>
        </article>
      ))}
    </>
  );
}
