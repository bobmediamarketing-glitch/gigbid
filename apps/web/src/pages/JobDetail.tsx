import { Link, useParams } from "react-router-dom";
import { Badge, Empty, ErrorBox, Loading, RiskBadge, StatusBadge, useData } from "../components/ui";
import { api, money, pct, unwrap } from "../lib/api";
import { useLive, useSession } from "../lib/session";

export default function JobDetail() {
  const { jobId = "" } = useParams();
  const { me } = useSession();
  const thread = `bid-u${me?.id}-${jobId}`;
  const run = useData(async () => {
    const r = await api.GET("/api/runs/{thread_id}", { params: { path: { thread_id: thread } } });
    return r.response.status === 404 ? null : unwrap(r);
  }, [thread]);
  useLive((e) => {
    if (e.thread_id === thread && (e.type === "run" || e.type === "node")) run.reload();
  });

  async function analyse() {
    unwrap(await api.POST("/api/jobs/{job_id}/analyze", { params: { path: { job_id: jobId } } }));
    run.reload();
  }

  if (run.loading) return <Loading rows={4} />;
  if (run.error) return <ErrorBox error={run.error} retry={run.reload} />;
  const v = run.data;
  if (!v)
    return (
      <Empty title="Not analysed yet">
        <p>GigBid hasn't looked at job {jobId}.</p>
        <button className="primary" onClick={analyse}>Analyse this job</button>
      </Empty>
    );
  const job = v.job as Record<string, any> | null;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{job?.title ?? jobId}</h1>
          <div className="row">
            <StatusBadge status={v.status} />
            {v.decision && <Badge tone={v.decision.action === "bid" ? "ok" : v.decision.action === "watch" ? "info" : ""}>Recommended: {v.decision.action}</Badge>}
            {v.risk && <RiskBadge score={v.risk.scam_score} type={v.risk.scam_type} injection={v.risk.injection_detected} />}
          </div>
        </div>
        <div className="row">
          <Link className="btn" to={`/runs/${thread}`}>Agent run</Link>
          {v.pending && <Link className="btn primary" to={`/studio/${thread}`}>Review proposal</Link>}
        </div>
      </div>
      {v.status === "running" && <div className="banner info"><span className="spinner" /> Analysing: results appear as each agent finishes.</div>}

      <div className="grid-2">
        <div>
          <section className="card" aria-labelledby="h-decision">
            <h2 id="h-decision">Bid or skip</h2>
            {v.decision ? (
              <>
                <p><strong>{v.decision.action.toUpperCase()}</strong> <span className="muted">(confidence {pct(v.decision.confidence)})</span></p>
                <ul>{v.decision.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              </>
            ) : <p className="muted">Waiting for the analysis.</p>}
          </section>

          <section className="card" aria-labelledby="h-matrix">
            <h2 id="h-matrix">Requirements and the work that proves them</h2>
            {v.fit ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Requirement</th><th>Covered</th><th>Evidence</th></tr></thead>
                  <tbody>
                    {v.fit.per_requirement.map((r) => (
                      <tr key={r.requirement}>
                        <td>{r.requirement}</td>
                        <td>{r.covered ? <Badge tone="ok">yes</Badge> : <Badge tone="warn">no proof</Badge>}</td>
                        <td>
                          {(r.evidence ?? []).length === 0 && <span className="muted small">nothing in the portfolio</span>}
                          {(r.evidence ?? []).map((e) => (
                            <div key={e.id} className="small"><span className="mono">{e.id}</span> {e.title} <span className="muted">({e.type.replace("_", " ")})</span></div>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="small muted">Coverage {pct(v.fit.coverage)}{v.fit.in_domain ? "" : " · outside your categories"}</p>
              </div>
            ) : <Loading rows={1} />}
          </section>

          <section className="card" aria-labelledby="h-post">
            <h2 id="h-post">Job post</h2>
            <p style={{ whiteSpace: "pre-wrap" }}>{job?.description}</p>
            {v.risk?.injection_spans?.length ? (
              <div className="banner warn small">
                <div><strong>Hidden instructions removed before any agent read this post:</strong>
                  <ul>{v.risk.injection_spans.map((s) => <li key={s} className="mono">{s}</li>)}</ul></div>
              </div>
            ) : null}
          </section>
        </div>

        <div>
          <section className="card" aria-labelledby="h-spec">
            <h2 id="h-spec">What the client needs</h2>
            {v.spec ? (
              <>
                <p>{v.spec.goal}</p>
                {(v.spec.implied_skills ?? []).length > 0 && <p className="small">Implied skills: {(v.spec.implied_skills ?? []).map((s) => <Badge key={s} tone="info">{s}</Badge>)}</p>}
                {v.spec.read_check_word && <p className="small">Client asks proposals to start with <strong>"{v.spec.read_check_word}"</strong>.</p>}
                {v.spec.vague && <p className="small"><Badge tone="warn">vague post</Badge></p>}
                <p className="small muted">Budget {money(v.spec.budget_min, v.spec.budget_type)}-{money(v.spec.budget_max, v.spec.budget_type)} ({v.spec.budget_type})</p>
              </>
            ) : <Loading rows={1} />}
          </section>

          <section className="card" aria-labelledby="h-risk">
            <h2 id="h-risk">Risk report</h2>
            {v.risk ? (
              <>
                <p>Scam score <strong>{v.risk.scam_score.toFixed(2)}</strong>{v.risk.scam_type ? ` (${v.risk.scam_type.replace("_", " ")})` : ""}</p>
                {(v.risk.red_flags ?? []).length ? <ul className="small">{(v.risk.red_flags ?? []).map((f) => <li key={f}>{f}</li>)}</ul> : <p className="small muted">No red flags.</p>}
                {v.client && <p className="small muted">Client: {String((v.client as any).country ?? "")}, {(v.client as any).payment_verified ? "payment verified" : "payment NOT verified"}, hire rate {pct((v.client as any).hire_rate)}</p>}
              </>
            ) : <Loading rows={1} />}
          </section>

          {v.quote && (
            <section className="card" aria-labelledby="h-price">
              <h2 id="h-price">Price</h2>
              <p className="stat">{money(v.quote.amount, v.quote.bid_type)}</p>
              <p className="small">{v.quote.rationale}</p>
              {v.quote.market && Object.keys(v.quote.market).length > 0 && (
                <p className="small muted">Market p25 {money(v.quote.market.p25)} · p50 {money(v.quote.market.p50)} · p75 {money(v.quote.market.p75)} · your floor {money(v.quote.floor)}</p>
              )}
              <p className="small muted">{v.quote.connects_cost} Connects to submit</p>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
