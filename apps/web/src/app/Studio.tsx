import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ClaimText, DiffView } from "../components/EvidenceHover";
import { Badge, Empty, ErrorBox, Loading, RiskBadge, StatusBadge, useData } from "../components/ui";
import { api, money, unwrap } from "../lib/client";
import { useLive, useSession } from "../lib/session";

type Pending = Record<string, any>;

export default function Studio() {
  const { threadId = "" } = useParams();
  const { health } = useSession();
  const nav = useNavigate();
  const run = useData(async () => unwrap(await api.GET("/api/runs/{thread_id}", { params: { path: { thread_id: threadId } } })), [threadId]);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [bid, setBid] = useState<string>("");
  const [reason, setReason] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [regen, setRegen] = useState<{ i: number; text: string } | null>(null);

  useLive((e) => {
    if (e.thread_id === threadId && e.type === "run") run.reload();
  });
  const p = run.data?.pending as Pending | null | undefined;
  useEffect(() => {
    if (p) {
      setText(p.cover_letter);
      setBid(String(p.bid_amount));
      setEditing(false);
      setRegen(null);
    }
  }, [p?.cover_letter, p?.bid_amount]);

  async function resume(body: Record<string, unknown>, key: string) {
    setBusy(key);
    setErr(null);
    try {
      unwrap(await api.POST("/api/runs/{thread_id}/resume", { params: { path: { thread_id: threadId } }, body: body as any }));
      setShowReject(false);
      run.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  }

  async function regenerate(i: number) {
    setBusy(`regen-${i}`);
    setErr(null);
    try {
      const r = unwrap(await api.POST("/api/runs/{thread_id}/regenerate", { params: { path: { thread_id: threadId } }, body: { paragraph: i } }));
      setRegen({ i, text: r.text });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  }

  if (run.loading) return <Loading rows={5} label="Loading draft" />;
  if (run.error) return <ErrorBox error={run.error} retry={run.reload} />;
  const v = run.data!;
  if (!p || p.type !== "approve_proposal") {
    return (
      <Empty title={v.status === "running" ? "Working on it" : "Nothing waiting for approval"}>
        <p>
          Status: <StatusBadge status={v.status} />
        </p>
        {v.status === "running" && <p><span className="spinner" /> The run continues in the background; this page updates by itself.</p>}
        {v.submission && <p>Proposal <span className="mono">{String(v.submission.id)}</span> was submitted.</p>}
        <div className="row" style={{ justifyContent: "center" }}>
          <Link className="btn" to={`/runs/${threadId}`}>Open the agent run</Link>
          <button onClick={() => nav("/inbox")}>Back to inbox</button>
        </div>
      </Empty>
    );
  }
  const evidence: Record<string, string> = { ...(v.evidence ?? {}), ...(p.evidence ?? {}) };
  const paras: string[] = String(p.cover_letter_with_citations).split("\n\n");
  const crit = p.critique as Pending | null;
  const comp = p.compliance as Pending | null;
  const ver = p.verification as Pending | null;
  const removed = (ver?.removed ?? []) as { sentence: string; reason: string }[];
  const textChanged = text.trim() !== String(p.cover_letter).trim() || Number(bid) !== Number(p.bid_amount);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Proposal studio</h1>
          <p>
            {p.job_title} · <Link to={`/jobs/${p.job_id}`}>job details</Link> · <Link to={`/runs/${threadId}`}>agent run</Link>
          </p>
        </div>
        <StatusBadge status={v.status} />
      </div>
      {err ? <ErrorBox error={err} /> : null}
      <div className="grid-2">
        <div>
          <section className="card" aria-labelledby="h-draft">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2 id="h-draft">Cover letter</h2>
              <button onClick={() => setEditing(!editing)} aria-pressed={editing} data-testid="toggle-edit">
                {editing ? "Preview with evidence" : "Edit text"}
              </button>
            </div>
            {editing ? (
              <>
                <label htmlFor="draft-text" className="visually-hidden">Cover letter text</label>
                <textarea id="draft-text" value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 320 }} data-testid="draft-text" />
                <p className="small muted">Your edit is re-checked by Compliance before it can be sent, and repeated edit patterns become style rules (Settings → Memory).</p>
              </>
            ) : (
              <div className="draft-preview" data-testid="draft-preview">
                {paras.map((para, i) => (
                  <div className="para" key={i}>
                    <ClaimText text={para} evidence={evidence} />
                    <button
                      className="regen"
                      onClick={() => regenerate(i)}
                      disabled={!health?.llm_available || busy === `regen-${i}`}
                      title={health?.llm_available ? "Rewrite this paragraph" : "Needs a model API key"}
                    >
                      {busy === `regen-${i}` ? <span className="spinner" /> : "Regenerate"}
                    </button>
                    {regen?.i === i && (
                      <div className="note ok">
                        <p className="small"><strong>Suggested rewrite:</strong> {regen.text}</p>
                        <button onClick={() => {
                          const all = String(p.cover_letter).split("\n\n");
                          all[i] = regen.text.replace(/\s?\[[a-z_]+-(?:cs|repo|rev|prop)-\d+\]/g, "");
                          setText(all.join("\n\n"));
                          setEditing(true);
                          setRegen(null);
                        }}>Use it</button>
                      </div>
                    )}
                    <hr style={{ margin: "6px 0" }} />
                  </div>
                ))}
              </div>
            )}
          </section>

          {p.screening_questions?.length > 0 && (
            <section className="card" aria-labelledby="h-screen">
              <h2 id="h-screen">Screening answers</h2>
              {p.screening_questions.map((q: string, i: number) => (
                <div key={q}>
                  <h3>{q}</h3>
                  <p><ClaimText text={p.screening_answers?.[i] ?? ""} evidence={evidence} /></p>
                </div>
              ))}
            </section>
          )}

          {v.edits.filter((e) => e.diff).length > 0 && (
            <section className="card" aria-labelledby="h-edits">
              <h2 id="h-edits">Your earlier edits</h2>
              {v.edits.filter((e) => e.diff).map((e) => <DiffView key={e.at} diff={e.diff!} />)}
            </section>
          )}

          <div className="card sticky-actions" role="group" aria-label="Decision">
            {textChanged ? (
              <button className="primary" disabled={!!busy} data-testid="save-edit"
                onClick={() => resume({ action: "edit", cover_letter: text, bid_amount: Number(bid) || undefined }, "edit")}>
                {busy === "edit" && <span className="spinner" />} Save edit and re-check
              </button>
            ) : (
              <button className="primary" disabled={!!busy || comp?.allowed === false} data-testid="approve"
                onClick={() => resume({ action: "approve" }, "approve")}>
                {busy === "approve" && <span className="spinner" />} Approve and submit ({p.connects_cost} Connects)
              </button>
            )}
            <button className="danger" onClick={() => setShowReject(!showReject)} aria-expanded={showReject} data-testid="reject-open">
              Reject
            </button>
            {showReject && (
              <form className="row" style={{ flex: "1 1 100%" }} onSubmit={(e) => { e.preventDefault(); resume({ action: "reject", note: reason }, "reject"); }}>
                <label htmlFor="reason" className="visually-hidden">Reason for rejecting</label>
                <input id="reason" placeholder="Why? (e.g. client looks unresponsive)" value={reason} onChange={(e) => setReason(e.target.value)} required style={{ flex: 1 }} data-testid="reject-reason" />
                <button className="danger" type="submit" disabled={!reason.trim() || !!busy} data-testid="reject-confirm">Reject proposal</button>
              </form>
            )}
          </div>
        </div>

        <div>
          <section className="card" aria-labelledby="h-send">
            <h2 id="h-send">What will be sent</h2>
            <label htmlFor="bid">Bid ({p.bid_type})</label>
            <input id="bid" type="number" min={1} value={bid} onChange={(e) => setBid(e.target.value)} />
            <p className="small muted">{p.price_rationale}</p>
            <p className="small">
              Cost: <strong>{p.connects_cost} Connects</strong>
              {p.connects_balance_after !== null && p.connects_balance_after !== undefined && <> · balance after: {p.connects_balance_after}</>}
            </p>
            <p className="small muted">Dry-run preview from the marketplace: nothing has been sent yet.</p>
          </section>

          <section className="card" aria-labelledby="h-critic">
            <h2 id="h-critic">Critic</h2>
            {crit ? (
              <>
                <p>Score <strong>{Math.round(crit.score * 100)}</strong>/100 {crit.passed ? <Badge tone="ok">passed</Badge> : <Badge tone="warn">below the bar</Badge>}</p>
                {crit.issues.map((i: string) => <div key={i} className="note warn">{i}</div>)}
                {crit.suggestions.map((i: string) => <div key={i} className="note">{i}</div>)}
                {!crit.issues.length && <p className="small muted">No issues.</p>}
              </>
            ) : <p className="muted small">No critique.</p>}
          </section>

          <section className="card" aria-labelledby="h-comp">
            <h2 id="h-comp">Compliance</h2>
            {comp ? (
              <>
                <p>{comp.allowed ? <Badge tone="ok">allowed</Badge> : <Badge tone="bad">blocked</Badge>} <span className="small muted">{comp.policy_version}</span></p>
                {comp.violations.map((x: Pending, i: number) => (
                  <div key={i} className={`note ${x.action === "block" ? "bad" : "warn"}`}>
                    <strong>{x.rule}</strong> ({x.action}): <span className="mono">{x.match}</span>
                  </div>
                ))}
                {!comp.violations.length && <p className="small muted">No policy issues.</p>}
              </>
            ) : <p className="small muted">Re-checking...</p>}
          </section>

          <section className="card" aria-labelledby="h-verify">
            <h2 id="h-verify">Claim check</h2>
            {ver ? (
              <p className="small">{ver.checked} claims checked: {ver.supported} supported, {ver.partly ?? 0} partly, {ver.unsupported ?? removed.length} removed.</p>
            ) : null}
            {removed.map((r) => (
              <div key={r.sentence} className="note bad small"><s>{r.sentence}</s><br />{r.reason}</div>
            ))}
          </section>

          {p.risk && (
            <section className="card" aria-labelledby="h-risk2">
              <h2 id="h-risk2">Risk</h2>
              <RiskBadge score={p.risk.scam_score} type={p.risk.scam_type} injection={p.risk.injection_detected} />
              <ul className="small">{(p.risk.red_flags as string[]).map((f) => <li key={f}>{f}</li>)}</ul>
            </section>
          )}
          <p className="small muted">Bid {money(Number(bid), p.bid_type)} · decision: {(p.decision?.reasons ?? []).join("; ")}</p>
        </div>
      </div>
    </>
  );
}
