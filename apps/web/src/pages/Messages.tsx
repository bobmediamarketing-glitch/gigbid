import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ClaimText } from "../components/Evidence";
import { Badge, Empty, ErrorBox, Loading, StatusBadge, useData } from "../components/ui";
import { api, unwrap } from "../lib/api";
import { useLive } from "../lib/session";

export default function Messages() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("thread");
  const threads = useData(async () => unwrap(await api.GET("/api/threads")));
  useLive((e) => {
    if (e.type === "run" || e.type === "pipeline") threads.reload();
  });
  const t = threads.data?.items.find((x) => x.id === selected) ?? null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Messages</h1>
          <p>Client conversations. GigBid drafts a reply for each new client message; you approve before anything is sent.</p>
        </div>
      </div>
      {threads.error ? <ErrorBox error={threads.error} retry={threads.reload} /> : null}
      {threads.loading && <Loading rows={3} />}
      {threads.data?.items.length === 0 && <Empty title="No conversations yet">When a client replies to a proposal, the thread shows up here.</Empty>}
      {threads.data && threads.data.items.length > 0 && (
        <div className="threads">
          <div role="list" aria-label="Threads">
            {threads.data.items.map((x) => (
              <button key={x.id} role="listitem" className={`thread-item ${x.id === selected ? "active" : ""}`} onClick={() => setParams({ thread: x.id })} aria-current={x.id === selected}>
                <strong>{x.job_title ?? x.job_id}</strong> {x.pending_run && <Badge tone="warn">reply ready</Badge>}
                <div className="small muted">{x.stage} · {x.last_message?.body.slice(0, 70)}</div>
              </button>
            ))}
          </div>
          <div>{t ? <ThreadView key={t.id} t={t} onDone={threads.reload} /> : <Empty title="Pick a conversation" />}</div>
        </div>
      )}
    </>
  );
}

function ThreadView({ t, onDone }: { t: any; onDone: () => void }) {
  const run = useData(async () => (t.pending_run ? unwrap(await api.GET("/api/runs/{thread_id}", { params: { path: { thread_id: t.pending_run } } })) : null), [t.pending_run]);
  const p = run.data?.pending as Record<string, any> | null | undefined;
  const [body, setBody] = useState("");
  const [slots, setSlots] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (p) {
      setBody(p.reply);
      setSlots((p.slots_offered ?? []).map((_: unknown, i: number) => i));
    }
  }, [p?.reply]);

  async function resume(payload: Record<string, unknown>) {
    setBusy(true);
    setErr(null);
    try {
      unwrap(await api.POST("/api/runs/{thread_id}/resume", { params: { path: { thread_id: t.pending_run } }, body: payload as any }));
      onDone();
      run.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }
  async function draft() {
    setBusy(true);
    try {
      unwrap(await api.POST("/api/threads/{thread_id}/draft", { params: { path: { thread_id: t.id } } }));
      setTimeout(onDone, 1500);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="thread-title">
      <h2 id="thread-title">{t.job_title ?? t.job_id} <Badge>{t.stage}</Badge></h2>
      <div aria-live="polite">
        {t.messages.map((m: any) => (
          <div key={m.id} className={`bubble ${m.sender}`}>
            <div className="small muted">{m.sender === "client" ? "Client" : "You"}</div>
            {m.body}
          </div>
        ))}
      </div>
      <hr />
      {err ? <ErrorBox error={err} /> : null}
      {!t.pending_run && (
        <button onClick={draft} disabled={busy}>{busy && <span className="spinner" />} Draft a reply</button>
      )}
      {run.loading && t.pending_run && <Loading rows={1} />}
      {p && (
        <div data-testid="reply-approval">
          <h3>Suggested reply <Badge tone="info">{p.intent?.kind?.replace("_", " ")}</Badge> {run.data && <StatusBadge status={run.data.status} />}</h3>
          {p.injections_removed?.length > 0 && <div className="banner warn small">Removed hidden instructions from the client's message: {p.injections_removed.join(" ")}</div>}
          <div className="draft-preview card tight"><ClaimText text={p.reply_with_citations} evidence={p.evidence ?? {}} /></div>
          {p.slots_offered?.length > 0 && (
            <fieldset>
              <legend>Interview slots to offer (held as tentative on your calendar after sending)</legend>
              {p.slots_offered.map((s: any, i: number) => (
                <label key={s.start} className="choice">
                  <input type="checkbox" checked={slots.includes(i)} onChange={(e) => setSlots(e.target.checked ? [...slots, i] : slots.filter((x) => x !== i))} />
                  {new Date(s.start).toLocaleString(undefined, { timeZone: s.timezone, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} ({s.timezone})
                </label>
              ))}
            </fieldset>
          )}
          <label htmlFor="reply-body">Edit before sending</label>
          <textarea id="reply-body" value={body} onChange={(e) => setBody(e.target.value)} />
          {p.compliance && !p.compliance.allowed && <div className="note bad">Blocked: {p.compliance.violations.map((v: any) => v.rule).join(", ")}</div>}
          {p.compliance?.violations?.length > 0 && p.compliance.allowed && <div className="note warn small">Auto-fixed: {p.compliance.violations.map((v: any) => v.rule).join(", ")}</div>}
          <div className="row" style={{ marginTop: 10 }}>
            {body.trim() !== String(p.reply).trim() ? (
              <button className="primary" disabled={busy} onClick={() => resume({ action: "edit", body })}>Save edit and re-check</button>
            ) : (
              <button className="primary" disabled={busy || p.compliance?.allowed === false} onClick={() => resume({ action: "approve", slots })} data-testid="send-reply">
                Approve and send
              </button>
            )}
            <button className="danger" disabled={busy} onClick={() => resume({ action: "reject", note: "not sending this reply" })}>Discard</button>
          </div>
        </div>
      )}
    </section>
  );
}
