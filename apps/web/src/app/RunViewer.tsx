import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorBox, Loading, StatusBadge, useData } from "../components/ui";
import { api, unwrap } from "../lib/client";
import { useLive } from "../lib/session";

const BID = ["intake", "analyst", "risk", "matcher", "decide", "pricing", "writer", "verify", "critic", "compliance", "approval", "submit"];
const CONV = ["load_thread", "classify", "gather", "draft_reply", "verify_reply", "check_reply", "approve_reply", "send_reply"];
const LABEL: Record<string, string> = {
  intake: "Intake (job, client, policy; injections stripped)", analyst: "Job Analyst", risk: "Risk Assessor", matcher: "Fit Matcher",
  decide: "Bid / watch / skip", pricing: "Pricing Strategist", writer: "Proposal Writer", verify: "Claim verification", critic: "Critic",
  compliance: "Compliance Guard", approval: "Your approval", submit: "Submit (idempotent)", load_thread: "Read thread", classify: "Classify intent",
  gather: "Evidence / free slots", draft_reply: "Draft reply", verify_reply: "Claim verification", check_reply: "Compliance", approve_reply: "Your approval", send_reply: "Send + calendar holds",
};

export default function RunViewer() {
  const { threadId = "" } = useParams();
  const run = useData(async () => unwrap(await api.GET("/api/runs/{thread_id}", { params: { path: { thread_id: threadId } } })), [threadId]);
  const [live, setLive] = useState<{ node: string; ms?: number; at: number }[]>([]);
  useLive((e) => {
    if (e.thread_id !== threadId) return;
    if (e.type === "node" && e.node) setLive((l) => [...l, { node: e.node!, ms: e.ms as number | undefined, at: Date.now() }]);
    if (e.type === "run") run.reload();
  });
  if (run.loading) return <Loading rows={4} />;
  if (run.error) return <ErrorBox error={run.error} retry={run.reload} />;
  const v = run.data!;
  const order = v.kind === "bid" ? BID : CONV;
  const doneNodes = new Map<string, Record<string, any>>();
  for (const t of v.trace ?? []) { const n = String(t.node); if (!doneNodes.has(n)) doneNodes.set(n, t); }
  for (const l of live) if (!doneNodes.has(l.node)) doneNodes.set(l.node, { node: l.node, ms: l.ms });
  const waitingAt = v.pending ? (v.kind === "bid" ? "approval" : "approve_reply") : null;
  const failed = ["dead_letter", "needs_attention", "blocked"].includes(v.status);
  const nextNode = v.status === "running" ? order.find((n) => !doneNodes.has(n)) : null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Agent run</h1>
          <p className="mono">{threadId}</p>
        </div>
        <div className="row">
          <StatusBadge status={v.status} />
          {v.pending && v.kind === "bid" && <Link className="btn primary" to={`/studio/${threadId}`}>Review proposal</Link>}
          {v.trace_url && <a className="btn" href={v.trace_url} target="_blank" rel="noreferrer">Full trace</a>}
        </div>
      </div>
      <div className="grid-2">
        <section className="card" aria-labelledby="h-steps">
          <h2 id="h-steps">Progress</h2>
          <ol className="steps" aria-live="polite">
            {order.map((n) => {
              const t = doneNodes.get(n);
              const state = n === waitingAt ? "active" : t ? "done" : n === nextNode ? "active" : "";
              return (
                <li key={n}>
                  <span className={`dot ${failed && !t && n === nextNode ? "fail" : state}`} aria-hidden />
                  <span>
                    {LABEL[n] ?? n}
                    {n === waitingAt && <span className="small muted"> · waiting for you</span>}
                    {t?.note && <div className="small muted">{t.note}</div>}
                    {t?.retries && <div className="small muted">retried {t.retries}x</div>}
                  </span>
                  <span className="small muted mono">{t?.ms !== undefined && t?.ms !== null ? `${Math.round(t.ms)} ms` : ""}{t?.model && t.model !== "rules" ? ` · ${t.model}` : ""}</span>
                </li>
              );
            })}
          </ol>
          <p className="small muted" style={{ marginTop: 8 }}>{v.steps} steps · {v.tokens} tokens · ${v.usd.toFixed(4)}</p>
          {v.errors.length > 0 && (
            <div className="banner warn small"><div><strong>Notes and errors</strong><ul>{v.errors.map((e) => <li key={e}>{e}</li>)}</ul></div></div>
          )}
        </section>
        <section className="card" aria-labelledby="h-hist">
          <h2 id="h-hist">Checkpoint history</h2>
          <p className="small muted">Every step is checkpointed; any job can be replayed from any of these points.</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Step</th><th>Next</th><th>Status</th></tr></thead>
              <tbody>
                {v.history.map((h) => (
                  <tr key={h.checkpoint_id ?? h.step}>
                    <td className="mono">{h.step}</td>
                    <td className="small">{h.next.join(", ") || "end"}</td>
                    <td className="small">{h.status ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}
