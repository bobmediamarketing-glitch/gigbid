// Typed API client generated from FastAPI's OpenAPI schema (npm run gen:api). Every request and
// response shape below is checked against the backend at compile time.
import createClient from "openapi-fetch";
import type { components, paths } from "./api-types";

export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });

export type S = components["schemas"];
export type Me = S["Me"];
export type Settings = S["Settings"];
export type JobCard = S["JobCard"];
export type RunView = S["RunView"];
export type RunSummary = S["RunSummary"];

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Unwrap an openapi-fetch result: return data or throw an ApiError with the server's message. */
export function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  if (res.error !== undefined || !res.response.ok) {
    const e = res.error as { detail?: unknown } | undefined;
    let msg = `Request failed (${res.response.status})`;
    if (typeof e?.detail === "string") msg = e.detail;
    else if (Array.isArray(e?.detail)) msg = e.detail.map((d: { msg?: string }) => d.msg).join("; ");
    throw new ApiError(res.response.status, msg);
  }
  return res.data as T;
}

export function money(n: number | null | undefined, type?: string | null): string {
  if (n === null || n === undefined) return "-";
  const s = `$${Math.round(n).toLocaleString()}`;
  return type === "hourly" ? `${s}/h` : s;
}

export function pct(n: number | null | undefined): string {
  return n === null || n === undefined ? "-" : `${Math.round(n * 100)}%`;
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export const STATUS_LABEL: Record<string, string> = {
  running: "Analysing",
  awaiting_approval: "Needs your approval",
  submitted: "Submitted",
  pending_platform_confirmation: "Confirm on Upwork",
  skipped: "Skipped",
  skip_suggested: "Skip suggested",
  watching: "Watching",
  rejected: "Rejected",
  blocked: "Blocked by policy",
  queued: "Queued (marketplace down)",
  needs_attention: "Needs attention",
  dead_letter: "Failed",
  sent: "Sent",
  no_action: "Nothing to reply to",
};

export function statusTone(s: string): string {
  if (["awaiting_approval", "needs_attention", "skip_suggested", "pending_platform_confirmation"].includes(s)) return "warn";
  if (["submitted", "sent"].includes(s)) return "ok";
  if (["blocked", "dead_letter", "rejected"].includes(s)) return "bad";
  if (["running", "watching", "queued"].includes(s)) return "info";
  return "";
}
