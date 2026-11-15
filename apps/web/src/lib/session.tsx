import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, unwrap, type Me, type S } from "./api";

type Session = {
  me: Me | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  health: S["Health"] | null;
};

const Ctx = createContext<Session>({ me: null, loading: true, refresh: async () => {}, logout: async () => {}, health: null });

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState<S["Health"] | null>(null);

  const refresh = useCallback(async () => {
    const res = await api.GET("/api/auth/me");
    setMe(res.response.ok && res.data ? res.data : null);
    setLoading(false);
  }, []);

  const logout = useCallback(async () => {
    await api.POST("/api/auth/logout");
    setMe(null);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Health drives the "marketplace unavailable" banner; polled while signed in and onboarded.
  useEffect(() => {
    if (!me?.settings.onboarded) return;
    let stop = false;
    const tick = async () => {
      const res = await api.GET("/api/health");
      if (!stop && res.data) setHealth(res.data);
    };
    tick();
    const id = setInterval(tick, 20000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [me?.settings.onboarded]);

  return <Ctx.Provider value={{ me, loading, refresh, logout, health }}>{children}</Ctx.Provider>;
}

export const useSession = () => useContext(Ctx);

/** Live events from the API (Server-Sent Events). The browser reconnects on its own if the link drops. */
export type LiveEvent = { type: string; thread_id?: string; status?: string; node?: string; stage?: string; [k: string]: unknown };

const listeners = new Set<(e: LiveEvent) => void>();
let source: EventSource | null = null;

function ensureSource() {
  if (source) return;
  source = new EventSource("/api/stream");
  for (const t of ["node", "run", "pipeline"]) {
    source.addEventListener(t, (ev) => {
      const data = JSON.parse((ev as MessageEvent).data) as LiveEvent;
      listeners.forEach((l) => l(data));
    });
  }
}

export function useLive(handler: (e: LiveEvent) => void) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    ensureSource();
    const l = (e: LiveEvent) => ref.current(e);
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  }, []);
}

export async function load<T>(fn: () => Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  return unwrap(await fn());
}
