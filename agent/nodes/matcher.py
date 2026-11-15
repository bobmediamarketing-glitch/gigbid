"""Fit Matcher: for each requirement, retrieve proof from the Portfolio MCP server -> FitReport."""
from __future__ import annotations

import asyncio

from agent.handoffs import EvidenceRef, FitReport, RequirementFit
from agent.nodes import jobparse
from agent.nodes.base import Ctx, node
from agent.settings import section

PROOF_TYPES = ["case_study", "repo", "review"]  # past proposals are pitches, the CV is self-description
RANK = {"case_study": 0, "repo": 1, "review": 2}


@node("matcher")
async def matcher(state: dict, ctx: Ctx, usages: list) -> dict:
    job, clean, profile = state["job"], state["job_text_clean"], state["profile"]
    reqs = jobparse.requirements(job, clean)
    k = section("bid_graph").get("evidence_per_requirement", 3)

    async def one(r):
        res = await ctx.tools.call("matcher", "portfolio.search_evidence",
                                   {"requirement": r.text, "k": k, "filters": {"types": PROOF_TYPES}})
        items = res["items"]
        good = [i for i in items if set(r.skills) & {s.lower() for s in i["skills"]}] if r.skills else items[:1]
        good.sort(key=lambda i: RANK[i["type"]])  # a shipped project beats a repo, a repo beats a review
        ev = [EvidenceRef(id=i["id"], type=i["type"], title=i["title"], snippet=i["snippet"], score=i["score"],
                          uri=i.get("uri")) for i in good]
        return RequirementFit(requirement=r.text, covered=bool(ev), evidence=ev)

    per = list(await asyncio.gather(*(one(r) for r in reqs)))
    covered = sum(p.covered for p in per)
    return {"fit": FitReport(job_id=job["id"], coverage=round(covered / max(1, len(per)), 3), per_requirement=per,
                             in_domain=job.get("category") in profile.get("categories", []),
                             missing=[p.requirement for p in per if not p.covered])}
