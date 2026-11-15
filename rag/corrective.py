"""V8: corrective retrieval as a small LangGraph loop.

    retrieve -> grade --all requirements strong--> done
                  \\--some weak, first try--> rewrite (skill-hint expansion) -> retrieve
                  \\--still weak--> refuse those requirements (no evidence returned for them)

Grading uses the cross-encoder score of each requirement's best hit. A requirement that is
still weak after one re-query contributes no evidence, so the writer cannot claim it and the
Fit Matcher reports it as missing. If every requirement is weak the result is empty: the
signal the persona should skip the job.
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from rag.query import expand


class CState(TypedDict, total=False):
    query: str
    per_q: list            # [(query, ranking)]
    weak: list[int]        # indexes into per_q
    attempt: int
    refused: list[str]


def _graph(pipe, filters):
    from rag.index.rerank import Reranker

    rr = Reranker.get(pipe.cfg.reranker_model)

    def best(q: str, ranking) -> float:
        if not ranking:
            return float("-inf")
        if pipe.cfg.rerank:  # rankings already hold cross-encoder scores
            return ranking[0][1]
        return max(rr.score(q, [pipe.item_text[i] for i, _ in ranking[:3]]))

    def retrieve(s: CState) -> CState:
        return {"per_q": pipe.per_query(s["query"], filters), "attempt": 0}

    def grade(s: CState) -> CState:
        return {"weak": [j for j, (q, r) in enumerate(s["per_q"]) if best(q, r) < pipe.cfg.min_grade]}

    def rewrite(s: CState) -> CState:
        per_q = list(s["per_q"])
        allowed_docs = {d.id for d in pipe.corpus.all() if filters.allow(d)} if filters else None
        allowed = {str(i) for i, d in enumerate(pipe.unit_doc) if d in allowed_docs} if allowed_docs else None
        for j in s["weak"]:
            q = per_q[j][0]
            eq = expand(q)
            r = pipe.retrieve(eq, allowed)
            if pipe.cfg.rerank and r:
                r = pipe.rerank(q, r)  # grade against the original requirement, not the expansion
            per_q[j] = (q, r)
        return {"per_q": per_q, "attempt": s["attempt"] + 1}

    def refuse(s: CState) -> CState:
        weak = set(s["weak"])
        return {"per_q": [(q, [] if j in weak else r) for j, (q, r) in enumerate(s["per_q"])],
                "refused": [s["per_q"][j][0] for j in weak]}

    def route(s: CState) -> str:
        if not s["weak"]:
            return END
        return "rewrite" if s["attempt"] == 0 else "refuse"

    g = StateGraph(CState)
    g.add_node("retrieve", retrieve)
    g.add_node("grade", grade)
    g.add_node("rewrite", rewrite)
    g.add_node("refuse", refuse)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", route, ["rewrite", "refuse", END])
    g.add_edge("rewrite", "grade")
    g.add_edge("refuse", END)
    return g.compile()


def corrective_search(pipe, query: str, k: int, filters):
    out = _graph(pipe, filters).invoke({"query": query})
    pipe.last_refused = out.get("refused", [])
    return pipe.fuse(out["per_q"], k)
