"""Proposal Writer: grounded cover letter + screening answers with [evidence-id] markers -> ProposalDraft.

The LLM path writes from an evidence pack; the rule path assembles the same structure from
templates so the graph works without a model. Both cite only ids that are in the pack, and
claim verification (rag/verify.py) runs right after either one.
"""
from __future__ import annotations

import re

from agent import prompts
from agent.guards import fence
from agent.handoffs import Claim, ProposalDraft
from agent.memory import outcomes as outcome_memory
from agent.memory import style as style_memory
from agent.nodes.base import Ctx, node


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0].strip()


def _a(title: str) -> str:
    t = re.sub(r"\ba (?=[aeiou])", "an ", title[0].lower() + title[1:])
    return ("an " if t[0] in "aeiou" else "a ") + t


def _section(md: str, name: str) -> str:
    m = re.search(rf"##\s*{name}\s*\n(.+?)(?:\n##|\Z)", md, re.S | re.I)
    return " ".join(m.group(1).split()) if m else ""


async def evidence_pack(state: dict, ctx: Ctx) -> dict[str, dict]:
    """Best evidence per covered requirement, with full text for case studies (needed to verify numbers)."""
    pack: dict[str, dict] = {}
    for rf in state["fit"].per_requirement:
        for ev in rf.evidence[:1]:
            if ev.id in pack:
                pack[ev.id]["requirements"].append(rf.requirement)
                continue
            item = {"id": ev.id, "type": ev.type, "title": ev.title, "text": ev.snippet, "requirements": [rf.requirement]}
            if ev.type == "case_study":
                cs = await ctx.tools.call("writer", "portfolio.get_case_study", {"id": ev.id})
                item.update(text=cs["body"], skills=cs["skills"], result=_first_sentence(_section(cs["body"], "Result")))
            pack[ev.id] = item
    return pack


def _req_label(req: str, spec) -> str:
    r = next((x for x in spec.requirements if x.text == req), None)
    return ", ".join(r.skills) if r and r.skills else req[0].lower() + req[1:]


def rule_draft(state: dict, pack: dict[str, dict], revision: int) -> ProposalDraft:
    spec = state["spec"]
    goal = re.sub(r"\bour\b", "your", spec.goal)
    parts, claims = [], []
    lead = f"{spec.read_check_word.capitalize()}. " if spec.read_check_word else ""
    parts.append(f"{lead}You want {goal}, and that is the kind of system I build and hand over.")
    used = 0
    for item in pack.values():
        if used == 4:
            break
        label = ", ".join(_req_label(r, spec) for r in item["requirements"][:2])
        if item["type"] == "case_study":
            res = item.get("result") or ""
            res = res[0].lower() + res[1:].rstrip(".") if res else "it shipped to production"
            s = f"For {label}: on {_a(item['title'])}, I did this work and {res} [{item['id']}]."
        elif item["type"] == "repo":
            s = f"For {label}, one of my public repos shows how I structure this in real code [{item['id']}]."
        else:
            quote = _first_sentence(item["text"]).strip('"').rstrip(".")
            s = f"For {label}, a past client wrote: \"{quote}\" [{item['id']}]."
        parts.append(s)
        claims.append(Claim(text=s, evidence_ids=[item["id"]]))
        used += 1
    missing = state["fit"].missing[:2]
    if missing:
        labels = "; ".join(_req_label(m, spec) for m in missing)
        parts.append(f"For {labels}, I have less direct proof to show, so I would scope it in the first days "
                     "and tell you early if it needs more time.")
    steps = [", ".join(r.skills) or r.text for r in spec.requirements[:3]]
    if steps:
        parts.append(f"My plan: start with {steps[0]}" + (f", then {', then '.join(steps[1:])}" if steps[1:] else "")
                     + ", with tests at each step and a short handover note so your team can run and extend it "
                       "without me.")
    parts.append("In week one I would review your current setup, agree the scope and a success metric with you, "
                 "and ship a first working slice you can test.")
    parts.append("Would a short call this week to confirm the scope suit you?")
    best = next((v for v in pack.values() if v["type"] == "case_study"), next(iter(pack.values()), None))
    answers = [screening_answer(q, best, spec) for q in spec.screening_questions]
    return ProposalDraft(job_id=spec.job_id, cover_letter="\n\n".join([parts[0], " ".join(parts[1:-2]), *parts[-2:]]),
                         screening_answers=answers, claims=claims, revision=revision, model="rules",
                         prompt_version="writer@rules")


def screening_answer(q: str, best: dict | None, spec) -> str:
    ref = f"{best['title']} [{best['id']}]" if best else "a similar project"
    res = (best or {}).get("result", "")
    ql = q.lower()
    if "first week" in ql or "week one" in ql:
        return ("Days 1-2: read your current setup and agree one success metric. Days 3-5: build a first working "
                f"slice and share it for feedback, the same way I started on {ref}.")
    if "risk" in ql:
        req = spec.requirements[0].text if spec.requirements else "the integration"
        return (f"The riskiest part is usually {req[0].lower() + req[1:]}, because surprises there change the plan. "
                f"I would test it first with a small spike, as I did on {ref}.")
    if "link" in ql or "work" in ql or "example" in ql:
        return f"The closest example is {ref}. {res}".strip()
    return f"I would follow the approach from {ref}. {res}".strip()


@node("writer")
async def writer(state: dict, ctx: Ctx, usages: list) -> dict:
    revision = len(state.get("critiques", [])) + state.get("compliance_retries", 0)
    pack = await evidence_pack(state, ctx)
    evidence = {k: v["text"] for k, v in pack.items()}
    base = rule_draft(state, pack, revision)
    spec, profile, quote = state["spec"], state["profile"], state["quote"]
    notes = ""
    if state.get("critiques"):
        c = state["critiques"][-1]
        notes += "Revise the previous draft. Fix: " + "; ".join(c.issues + c.suggestions)
    if state.get("compliance") and not state["compliance"].allowed:
        notes += " Remove these policy violations: " + "; ".join(v["rule"] for v in state["compliance"].violations)
    # Long-term memory: learned style rules and what got replies in this category.
    who = state.get("user_id") or "local"
    srules = await style_memory.rules(ctx.store, who)
    oentry = await outcome_memory.lessons(ctx.store, who, spec.category)
    notes += " " + style_memory.as_instructions(srules) + " " + outcome_memory.notes(oentry)
    rc = (f"Start the cover letter with the word '{spec.read_check_word}'." if spec.read_check_word
          else "Do not start with any special word.")
    tmpl, version = prompts.load("writer")
    system = (tmpl.replace("{name}", profile["name"]).replace("{title}", profile["title"])
              .replace("{read_check}", rc).replace("{revision_notes}", notes))
    ev_txt = "\n\n".join(f"[{v['id']}] ({v['type']}) {v['title']}\nSupports: {'; '.join(v['requirements'])}\n"
                         f"{v['text'][:900]}" for v in pack.values()) or "(no evidence found)"
    user = (f"JOB SPEC: goal={spec.goal}; requirements={[r.text for r in spec.requirements]}; "
            f"screening={spec.screening_questions}; our price={quote.amount:g} {quote.bid_type}\n\n"
            f"JOB POST:\n{fence(state['job_text_clean'])}\n\nEVIDENCE:\n{ev_txt}\n\n"
            + (f"PREVIOUS DRAFT:\n{state['draft'].cover_letter}" if state.get("draft") else ""))
    draft, u = await ctx.llm.structured("writer", ProposalDraft, system, user)
    usages.append(u)
    if draft is None:
        draft = base
    else:
        draft = draft.model_copy(update={"job_id": spec.job_id, "revision": revision, "model": u.model,
                                         "prompt_version": version})
    if srules:  # learned rules hold on both paths, not just when the model follows instructions
        draft = draft.model_copy(update={"cover_letter": style_memory.apply(draft.cover_letter, srules,
                                                                            spec.read_check_word)})
    out = {"draft": draft, "evidence": evidence}
    if srules or oentry:
        out["trace"] = [{"node": "writer", "ms": 0.0,
                         "note": f"memory: {len(srules)} style rule(s), outcome lessons: {bool(oentry)}"}]
    if revision:
        out["revisions"] = 1
    return out
