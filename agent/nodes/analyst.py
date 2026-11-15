"""Job Analyst: job post -> JobSpec (requirements, implied skills, read-check word)."""
from __future__ import annotations

import json

from agent import prompts
from agent.guards import fence, read_check_word
from agent.handoffs import JobSpec
from agent.nodes import jobparse
from agent.nodes.base import Ctx, node


def rule_spec(job: dict, clean: str) -> JobSpec:
    reqs = jobparse.requirements(job, clean)
    implied = sorted({s for r in reqs for s in r.skills} - {s.lower() for s in job.get("skills", [])})
    return JobSpec(job_id=job["id"], goal=jobparse.goal(clean, job.get("category")), requirements=reqs,
                   implied_skills=implied, screening_questions=job.get("screening_questions", []),
                   read_check_word=read_check_word(clean), budget_type=job["budget"]["type"],
                   budget_min=job["budget"]["min"], budget_max=job["budget"]["max"], category=job.get("category"),
                   vague=jobparse.is_vague(job, clean))


@node("analyst")
async def analyst(state: dict, ctx: Ctx, usages: list) -> dict:
    job, clean = state["job"], state["job_text_clean"]
    base = rule_spec(job, clean)
    system, _ = prompts.load("analyst")
    meta = {k: job.get(k) for k in ("id", "category", "skills", "budget", "screening_questions", "experience_level")}
    spec, u = await ctx.llm.structured("analyst", JobSpec, system.replace("{skills}", ", ".join(jobparse.vocab())),
                                       f"Metadata: {json.dumps(meta)}\n\nPost:\n{fence(clean)}")
    usages.append(u)
    if spec is None:
        return {"spec": base}
    # Facts from metadata and the guard always win over the model.
    known = set(jobparse.vocab())
    for r in spec.requirements:
        r.skills = [s.lower() for s in r.skills if s.lower() in known]
    implied = {s.lower() for s in spec.implied_skills if s.lower() in known} | set(base.implied_skills)
    spec = spec.model_copy(update={
        "job_id": job["id"], "budget_type": base.budget_type, "budget_min": base.budget_min,
        "budget_max": base.budget_max, "category": base.category, "screening_questions": base.screening_questions,
        "read_check_word": base.read_check_word, "implied_skills": sorted(implied),
        "requirements": spec.requirements or base.requirements})
    return {"spec": spec}
