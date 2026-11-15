"""Critic: scores the draft against a client-eyed rubric; a failing draft goes back to the writer (max 2x)."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agent import prompts
from agent.handoffs import Critique
from agent.nodes.base import Ctx, node
from agent.settings import section

GENERIC_OPEN = re.compile(r"(?i)\b(dear (sir|madam|hiring manager)|hello sir|i am (very )?interested|perfect fit|"
                          r"passionate|hard-?working|i have (carefully )?read your (job|post))")


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


