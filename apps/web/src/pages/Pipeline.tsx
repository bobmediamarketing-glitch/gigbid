import { useState } from "react";
import { Link } from "react-router-dom";
import { Empty, ErrorBox, Loading, useData } from "../components/ui";
import { ago, api, money, unwrap } from "../lib/api";
import { useLive } from "../lib/session";

export default function Pipeline() {
  const pipe = useData(async () => unwrap(await api.GET("/api/pipeline")));
  const [moved, setMoved] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  useLive((e) => {
    if (e.type === "pipeline" || e.type === "run") {
      if (e.proposal_id) setMoved(String(e.proposal_id));
      pipe.reload();
    }
  });
  async function sync() {
    setSyncing(true);
    try {
      await api.POST("/api/sync");
      pipe.reload();
    } finally {
      setSyncing(false);
    }
  }
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Pipeline</h1>
          <p>Cards move by themselves as the marketplace reports views, replies, interviews and hires.</p>
        </div>
        <button onClick={sync} disabled={syncing}>{syncing && <span className="spinner" />} Check marketplace now</button>
      </div>
      {pipe.error ? <ErrorBox error={pipe.error} retry={pipe.reload} /> : null}
      {pipe.loading && <Loading rows={2} />}
      {pipe.data && pipe.data.cards.length === 0 && <Empty title="No proposals yet">Approve a draft and it appears here.</Empty>}
      {pipe.data && pipe.data.cards.length > 0 && (
        <div className="board" role="list" aria-label="Pipeline stages">
          {pipe.data.stages.map((st) => {
            const cards = pipe.data!.cards.filter((c) => c.stage === st);
            return (
              <section className="col" key={st} role="listitem" aria-label={`${st}: ${cards.length}`} data-testid={`col-${st}`}>
                <h3>{st} <span className="muted">{cards.length}</span></h3>
                {cards.map((c) => (
                  <div className={`kcard ${moved === c.id ? "moved" : ""}`} key={c.id}>
                    <Link to={c.stage === "drafted" ? `/studio/${c.thread_id}` : c.market_thread_id ? `/messages?thread=${c.market_thread_id}` : `/runs/${c.thread_id}`}>{c.title}</Link>
                    <div className="muted small">{c.category} · {money(c.bid_amount)} · {c.connects ?? 0} Connects</div>
                    <div className="muted small">{ago(c.updated_at)}</div>
                  </div>
                ))}
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}
