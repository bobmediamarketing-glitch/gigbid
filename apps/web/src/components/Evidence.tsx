import { useId } from "react";

const CITE = /\[([a-z_]+-(?:cs|repo|rev|prop)-\d+)\]/g;

/** Renders draft text; every sentence with a citation becomes a focusable span whose evidence shows on
 *  hover or keyboard focus. The markers themselves are hidden: the client never sees them. */
export function ClaimText({ text, evidence }: { text: string; evidence: Record<string, string> }) {
  const sentences = text.split(/(?<=[.!?\]"])\s+/);
  return (
    <>
      {sentences.map((s, i) => {
        const ids = [...s.matchAll(CITE)].map((m) => m[1]);
        const clean = s.replace(/\s?\[[a-z_]+-(?:cs|repo|rev|prop)-\d+\]/g, "");
        return ids.length ? <Claim key={i} text={clean} ids={ids} evidence={evidence} /> : <span key={i}>{clean} </span>;
      })}
    </>
  );
}

/** The part of an evidence item that proves the claim: the sentence holding the claim's number,
 *  else the case study's Result section, else the start of the item. */
function proof(claim: string, ev: string): string {
  const flat = ev.replace(/[#*]/g, "").replace(/\s+/g, " ").trim();
  const nums = claim.match(/\d+(?:\.\d+)?\s?%|\$\s?\d[\d,]*k?|\b\d+x\b/g) ?? [];
  const sentences = flat.split(/(?<=[.!?])\s+/);
  const hit = sentences.find((s) => nums.some((n) => s.replace(/\s/g, "").includes(n.replace(/\s/g, ""))));
  if (hit) return hit.replace(/^Result\s+/, "");
  const res = flat.match(/Result\s+(.{20,300}?)(?:\s(?:Date|Problem|What I built):|$)/);
  return res ? res[1] : flat.slice(0, 300) + (flat.length > 300 ? "..." : "");
}

function Claim({ text, ids, evidence }: { text: string; ids: string[]; evidence: Record<string, string> }) {
  const tipId = useId();
  const known = ids.filter((i) => evidence[i]);
  return (
    <>
      <span className={`claim ${known.length ? "" : "unsupported"}`} tabIndex={0} aria-describedby={tipId} data-testid="claim">
        {text}
        <span className="tip" role="tooltip" id={tipId}>
          {known.length === 0 && <strong>No evidence found for this claim.</strong>}
          {known.map((id) => (
            <span key={id} style={{ display: "block", marginBottom: 6 }}>
              <span className="mono">{id}</span>
              <br />
              {proof(text, evidence[id])}
            </span>
          ))}
        </span>
      </span>{" "}
    </>
  );
}

export function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="diff" aria-label="Changes you made">
      {diff.split("\n").map((l, i) => (
        <div key={i} className={l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : ""}>
          {l}
        </div>
      ))}
    </pre>
  );
}
