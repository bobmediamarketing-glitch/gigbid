"""Verify -> Critic -> Compliance Guard: the three checks every draft passes before a human sees it."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agent import prompts
from agent.guards import policy_rules
from agent.handoffs import ComplianceVerdict, Critique
from agent.nodes.base import Ctx, node
from agent.settings import section
from rag.verify import verify_text

GENERIC_OPEN = re.compile(r"(?i)\b(dear (sir|madam|hiring manager)|hello sir|i am (very )?interested|perfect fit|"
                          r"passionate|hard-?working|i have (carefully )?read your (job|post))")


# ---------------------------------------------------------------- verify
@node("verify")
async def verify(state: dict, ctx: Ctx, usages: list) -> dict:
    d, ev = state["draft"], state.get("evidence", {})
    text, v = verify_text(d.cover_letter, ev)
    answers, removed = [], list(v.removed)
    for a in d.screening_answers:
        t, va = verify_text(a, ev)
        answers.append(t or a)
        removed += va.removed
    removed_set = {r["sentence"] for r in removed}
    claims = [c.model_copy(update={"supported": c.text not in removed_set and all(i in ev for i in c.evidence_ids)})
              for c in d.claims]
    return {"draft": d.model_copy(update={"cover_letter": text, "screening_answers": answers, "claims": claims}),
            "verification": {"checked": v.checked, "supported": v.supported, "removed": removed}}


# ---------------------------------------------------------------- critic
class _LLMCritique(BaseModel):
    score: float = Field(ge=0, le=1)
    issues: list[str] = []
    suggestions: list[str] = []


def rubric(state: dict) -> Critique:
    d, spec = state["draft"], state["spec"]
    text = d.client_text()
    low = text.lower()
    issues, sugg, score = [], [], 0.0
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=2)
    opening = " ".join(first[:2])
    if GENERIC_OPEN.search(opening):
        issues.append("generic opening")
        sugg.append("open with the client's goal")
    else:
        score += 0.15
    skills = sorted({s for r in spec.requirements if r.must_have for s in r.skills})
    hit = [s for s in skills if s in low]
    cov = len(hit) / len(skills) if skills else 1.0
    score += 0.3 * cov
    if cov < 1:
        issues.append(f"does not mention: {', '.join(sorted(set(skills) - set(hit)))}")
    cites = len(set(re.findall(r"\[([a-z_]+-(?:cs|repo|rev|prop)-\d+)\]", d.cover_letter)))
    covered = sum(p.covered for p in state["fit"].per_requirement)
    if cites >= min(2, covered):
        score += 0.15
    else:
        issues.append("too few grounded claims")
        sugg.append("cite one more case study with a result")
    if len(d.screening_answers) >= len(spec.screening_questions):
        score += 0.1
    else:
        issues.append("unanswered screening questions")
    words = len(text.split())
    if 120 <= words <= 350:
        score += 0.1
    else:
        issues.append(f"length {words} words (want 150-300)")
    if not spec.read_check_word or low.lstrip().startswith(spec.read_check_word.lower()):
        score += 0.1
    else:
        issues.append(f"must start with '{spec.read_check_word}'")
    if "?" in text or "week one" in low or "first week" in low:
        score += 0.05
    else:
        sugg.append("end with a concrete next step")
    if not re.search(r"(?i)guarantee|100\s?%|full refund", text):
        score += 0.05
    removed = len(state.get("verification", {}).get("removed", []))
    if removed:
        score -= 0.05 * removed
        issues.append(f"{removed} unsupported claim(s) were removed by verification")
    score = round(max(0.0, min(1.0, score)), 3)
    return Critique(revision=d.revision, score=score, passed=score >= section("bid_graph")["critic_pass_score"],
                    issues=issues, suggestions=sugg)


@node("critic")
async def critic(state: dict, ctx: Ctx, usages: list) -> dict:
    c = rubric(state)
    tmpl, _ = prompts.load("critic")
    pass_score = section("bid_graph")["critic_pass_score"]
    spec = state["spec"]
    out, u = await ctx.llm.structured(
        "critic", _LLMCritique, tmpl.replace("{pass_score}", str(pass_score)),
        f"Requirements: {[r.text for r in spec.requirements]}\nScreening: {spec.screening_questions}\n"
        f"Read-check word: {spec.read_check_word}\n\nDRAFT:\n{state['draft'].cover_letter}\n\nANSWERS:\n"
        + "\n".join(state["draft"].screening_answers))
    usages.append(u)
    if out is not None:
        s = round((c.score + out.score) / 2, 3)
        c = c.model_copy(update={"score": s, "passed": s >= pass_score, "issues": c.issues + out.issues[:4],
                                 "suggestions": c.suggestions + out.suggestions[:4]})
    return {"critiques": [c]}


# ---------------------------------------------------------------- compliance
def _sentences(t: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", t)


def check_policy(text: str, answers: list[str], evidence: dict[str, str], injection_spans: list[str],
                 platform: dict) -> tuple[ComplianceVerdict, list[str]]:
    rules = policy_rules()
    allowed, vio = True, []
    pool = " ".join(evidence.values()).lower()

    def apply(t: str) -> str:
        nonlocal allowed
        for rule in rules["rules"]:
            for pat in rule["patterns"]:
                for m in list(re.finditer(pat, t)):
                    act = rule["action"]
                    if act == "verify_claims" and m.group(0).lower() in pool:
                        continue
                    vio.append({"rule": rule["id"], "action": act, "match": m.group(0)})
                    if act == "redact":
                        t = t.replace(m.group(0), "")
                    elif act == "rewrite":
                        t = " ".join(s for s in _sentences(t) if m.group(0) not in s)
                    else:  # block, verify_claims (unsupported)
                        allowed = False
        return re.sub(r"[ \t]{2,}", " ", t).strip()

    text = apply(text)
    answers = [apply(a) for a in answers]
    # Anything the injected text asked us to say must not appear in what we send.
    for span in injection_spans:
        for phrase in re.findall(r"'([^']{4,})'", span):
            if phrase.lower() in text.lower() or any(phrase.lower() in a.lower() for a in answers):
                allowed = False
                vio.append({"rule": "injection_echo", "action": "block", "match": phrase})
    props = (platform.get("raw") or {}).get("proposals", {})
    lo, hi = props.get("min_cover_letter_chars", 150), props.get("max_cover_letter_chars", 5000)
    if not lo <= len(text) <= hi:
        allowed = False
        vio.append({"rule": "platform_length", "action": "block", "match": f"{len(text)} chars (allowed {lo}-{hi})"})
    version = f"rules v{rules.get('version')} / platform v{platform.get('version', '?')}"
    return ComplianceVerdict(allowed=allowed, policy_version=version, violations=vio,
                             redacted_text=text), answers


@node("compliance")
async def compliance(state: dict, ctx: Ctx, usages: list) -> dict:
    d = state["draft"]
    verdict, answers = check_policy(d.client_text(), d.screening_answers, state.get("evidence", {}),
                                    state.get("injection_spans", []), state.get("policy", {}))
    out = {"compliance": verdict, "draft": d.model_copy(update={"screening_answers": answers})}
    if not verdict.allowed and not state.get("approval"):  # a human edit that fails goes back to the human
        if state.get("compliance_retries", 0) >= 1:
            out["status"] = "blocked"
        else:
            out["compliance_retries"] = 1
    return out
