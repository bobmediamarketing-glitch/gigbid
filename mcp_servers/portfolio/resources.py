"""Resource templates so a host can load full portfolio items by URI."""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP, store) -> None:
    def _doc(doc_id: str, kind: str) -> str:
        corpus, _ = store.get()
        d = corpus.get(doc_id)
        if not d or d.type != kind:
            raise ValueError(f"no {kind} {doc_id!r}")
        return d.text

    @mcp.resource("portfolio://case/{id}", mime_type="text/markdown", description="A case study in full")
    def case(id: str) -> str:
        return _doc(id, "case_study")

    @mcp.resource("portfolio://proposal/{id}", mime_type="application/json",
                  description="A past proposal with its outcome (won, replied, ignored)")
    def proposal(id: str) -> str:
        corpus, _ = store.get()
        d = corpus.get(id)
        if not d or d.type != "past_proposal":
            raise ValueError(f"no past proposal {id!r}")
        return json.dumps({"id": d.id, "job_title": d.title, "category": d.category, "outcome": d.outcome,
                           "date": d.date, "text": d.text})

    @mcp.resource("portfolio://repo/{id}", mime_type="text/markdown", description="A repo README plus code excerpts")
    def repo(id: str) -> str:
        return _doc(id, "repo")

    @mcp.resource("portfolio://review/{id}", mime_type="text/plain", description="A client review")
    def review(id: str) -> str:
        return _doc(id, "review")

    @mcp.resource("portfolio://cv", mime_type="text/markdown", description="The freelancer's CV")
    def cv() -> str:
        corpus, _ = store.get()
        d = next((x for x in corpus.all() if x.type == "cv"), None)
        return d.text if d else ""
