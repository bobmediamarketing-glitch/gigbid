import { useEffect, useState, type ReactNode } from "react";
import { ApiError, STATUS_LABEL, statusTone } from "../lib/client";

export function Badge({ tone = "", children, title }: { tone?: string; children: ReactNode; title?: string }) {
  return (
    <span className={`badge ${tone}`} title={title}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{STATUS_LABEL[status] ?? status}</Badge>;
}

export function Loading({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite">
      <span className="visually-hidden">{label}</span>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" />
      ))}
    </div>
  );
}

export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  const down = error instanceof ApiError && error.status === 503;
  return (
    <div className="banner bad" role="alert">
      <div>
        <strong>{down ? "The marketplace is unavailable." : "Something went wrong."}</strong> {msg}
        {retry && (
          <div style={{ marginTop: 6 }}>
            <button onClick={retry}>Try again</button>
          </div>
        )}
      </div>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty card">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

/** Small data hook: loads on mount and whenever `deps` change; exposes reload for live updates. */
export function useData<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(data === null);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, loading, reload: () => setN((x) => x + 1), setData };
}

export function Fit({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="muted small">not analysed</span>;
  return (
    <div className="fit" aria-label={`Fit ${Math.round(value * 100)} percent`}>
      <strong>{Math.round(value * 100)}%</strong> <span className="muted small">fit</span>
      <div className="fitbar">
        <div style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
    </div>
  );
}

export function RiskBadge({ score, type, injection }: { score?: number | null; type?: string | null; injection?: boolean }) {
  if (score === null || score === undefined) return null;
  return (
    <>
      {score > 0.5 ? (
        <Badge tone="bad" title={`Scam score ${score.toFixed(2)}`}>Scam risk{type ? `: ${type.replace("_", " ")}` : ""}</Badge>
      ) : score > 0.2 ? (
        <Badge tone="warn" title={`Scam score ${score.toFixed(2)}`}>Some risk</Badge>
      ) : (
        <Badge tone="ok" title={`Scam score ${score.toFixed(2)}`}>Low risk</Badge>
      )}
      {injection && <Badge tone="warn" title="Hidden instructions for AI tools were removed from this post">Injection removed</Badge>}
    </>
  );
}
