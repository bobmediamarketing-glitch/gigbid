"""Portfolio tools: search_evidence, get_case_study, list_skills."""
from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from rag.retriever import Filters

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
EvidenceType = Literal["cv", "case_study", "repo", "review", "past_proposal"]


class EvidenceFilters(BaseModel):
    types: list[EvidenceType] | None = Field(None, description="Restrict to these evidence types")
    outcomes: list[Literal["won", "replied", "ignored"]] | None = Field(None, description="Past proposals only")
    skills: list[str] | None = Field(None, max_length=20, description="Item must be tagged with any of these")
    industry: str | None = Field(None, max_length=60, description="Client industry, e.g. 'healthcare'")
    since: str | None = Field(None, description="ISO date; only items on or after it")


class EvidenceItem(BaseModel):
    id: str
    type: EvidenceType
    title: str
    source: str
    date: str | None
    outcome: str | None
    project: str | None
    industry: str | None
    skills: list[str]
    snippet: str
    score: float
    uri: str


class EvidenceResults(BaseModel):
    requirement: str
    retriever: str
    items: list[EvidenceItem]


class CaseStudy(BaseModel):
    id: str
    title: str
    date: str | None
    industry: str | None
    skills: list[str]
    body: str
    repo: str | None = None
    reviews: list[str] = []


class SkillCount(BaseModel):
    skill: str
    count: int
    evidence_ids: list[str]


class SkillList(BaseModel):
    skills: list[SkillCount]


URI = {"case_study": "portfolio://case/{}", "past_proposal": "portfolio://proposal/{}", "repo": "portfolio://repo/{}",
       "review": "portfolio://review/{}", "cv": "portfolio://cv"}


def _snippet(text: str, n: int = 400) -> str:
    t = " ".join(text.split())
    return t[:n] + ("..." if len(t) > n else "")


def register(mcp: FastMCP, store) -> None:
    @mcp.tool(annotations=READ)
    def search_evidence(
        requirement: Annotated[str, Field(min_length=2, max_length=2000,
                                          description="One job requirement or question to find proof for")],
        k: Annotated[int, Field(ge=1, le=20)] = 5,
        filters: EvidenceFilters | None = None,
    ) -> EvidenceResults:
        """Find portfolio evidence (case studies, repos, reviews, past proposals) that proves a requirement.
        Each item has type, source, date and, for past proposals, the outcome (won/replied/ignored)."""
        corpus, retriever = store.get()
        f = Filters(**filters.model_dump()) if filters else None
        hits = retriever.search(requirement, k=k, filters=f)
        return EvidenceResults(requirement=requirement, retriever=retriever.name, items=[
            EvidenceItem(id=h.doc.id, type=h.doc.type, title=h.doc.title, source=h.doc.source, date=h.doc.date,
                         outcome=h.doc.outcome, project=h.doc.project, industry=h.doc.industry, skills=h.doc.skills,
                         snippet=_snippet(h.doc.text), score=round(h.score, 4),
                         uri=URI[h.doc.type].format(h.doc.id)) for h in hits])

    @mcp.tool(annotations=READ)
    def get_case_study(id: Annotated[str, Field(min_length=1, max_length=80)]) -> CaseStudy:
        """Full case study with its linked repo and client reviews."""
        corpus, _ = store.get()
        d = corpus.get(id)
        if not d or d.type != "case_study":
            raise ToolError(f"[not_found] no case study {id!r}")
        linked = [x for x in corpus.all() if x.project == id]
        return CaseStudy(id=d.id, title=d.title, date=d.date, industry=d.industry, skills=d.skills, body=d.text,
                         repo=next((x.id for x in linked if x.type == "repo"), None),
                         reviews=[x.text for x in linked if x.type == "review"])

    @mcp.tool(annotations=READ)
    def list_skills() -> SkillList:
        """Every skill the portfolio can evidence, with how many items support it (most supported first)."""
        corpus, _ = store.get()
        by = defaultdict(list)
        for d in corpus.all():
            if d.type in ("cv", "past_proposal"):
                continue  # self-description and pitches are not proof
            for s in d.skills:
                by[s].append(d.id)
        rows = [SkillCount(skill=s, count=len(ids), evidence_ids=ids[:10]) for s, ids in by.items()]
        return SkillList(skills=sorted(rows, key=lambda r: (-r.count, r.skill)))
