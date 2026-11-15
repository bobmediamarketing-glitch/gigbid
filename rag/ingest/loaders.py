"""Portfolio loaders (Part B1): CV, case studies, repos, reviews and past proposals -> evidence documents.

Works on the persona corpora and on any freelancer's folder with this layout:

    cv.md | cv.pdf
    case_studies/*.md
    repos/<name>/README.md (+ any code files)
    reviews.json            [{"id", "text", "stars", "project"?}]
    past_proposals.jsonl    {"id", "text", "outcome": won|replied|ignored, "category"?}
    evidence_index.json     optional metadata keyed by id (skills, industry, date, ...)

Every document carries metadata: persona, type, project, skills, date, client industry
and, for proposals, outcome. `Corpus.refresh()` re-reads only files whose mtime changed,
which is how uploads in the UI are re-indexed incrementally.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".ipynb", ".txt", ".yaml", ".yml", ".toml"}
_VOCAB_FILE = Path(__file__).resolve().parents[2] / "gigsim" / "seed" / "skill_hints.json"


def skill_vocab() -> dict[str, str]:
    """Known skills -> implied phrasing. Used to tag documents that have no metadata."""
    if _VOCAB_FILE.exists():
        return json.loads(_VOCAB_FILE.read_text(encoding="utf-8"))
    return {}


@dataclass
class EvidenceDoc:
    id: str
    type: str                     # cv | case_study | repo | review | past_proposal
    title: str
    text: str
    source: str
    persona: str
    date: str | None = None
    outcome: str | None = None    # past proposals only: won | replied | ignored
    skills: list[str] = field(default_factory=list)
    industry: str | None = None
    project: str | None = None    # case study id this item belongs to (repos, reviews)
    category: str | None = None
    parts: dict[str, str] = field(default_factory=dict)  # repo: {"readme": .., "code": ..}

    def to_dict(self) -> dict:
        return asdict(self)


def _tag_skills(text: str, vocab: dict[str, str]) -> list[str]:
    low = text.lower()
    found = []
    for s, implied in vocab.items():
        if re.search(rf"(?<![\w]){re.escape(s)}(?![\w])", low) or implied.lower()[:30] in low:
            found.append(s)
    return found


def _md_field(md: str, name: str) -> str | None:
    m = re.search(rf"\*\*{name}:\*\*\s*([^\n]+?)\s*(?:\s\s)?$", md, re.M | re.I)
    return m.group(1).strip() if m else None


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)


class Corpus:
    def __init__(self, root: str | Path, persona: str | None = None) -> None:
        self.root = Path(root)
        self.persona = persona or self.root.name
        self.vocab = skill_vocab()
        self.docs: dict[str, EvidenceDoc] = {}
        self._mtimes: dict[str, float] = {}
        self.version = 0
        self.refresh()

    # -- public --
    def refresh(self) -> bool:
        """Reload if any file changed. Returns True if the corpus changed."""
        files = [p for p in self.root.rglob("*") if p.is_file()]
        mt = {str(p): p.stat().st_mtime for p in files}
        if mt == self._mtimes:
            return False
        self._mtimes = mt
        self.docs = {d.id: d for d in self._load()}
        self.version += 1
        return True

    def get(self, doc_id: str) -> EvidenceDoc | None:
        return self.docs.get(doc_id)

    def all(self) -> list[EvidenceDoc]:
        return list(self.docs.values())

    # -- loading --
    def _meta(self) -> dict[str, dict]:
        f = self.root / "evidence_index.json"
        return {m["id"]: m for m in json.loads(f.read_text(encoding="utf-8"))} if f.exists() else {}

    def _load(self) -> list[EvidenceDoc]:
        meta, out = self._meta(), []
        P = self.persona

        def enrich(d: EvidenceDoc) -> EvidenceDoc:
            m = meta.get(d.id, {})
            d.skills = m.get("skills") or d.skills or _tag_skills(d.text, self.vocab)
            d.industry = m.get("industry", d.industry)
            d.date = m.get("date", d.date)
            d.project = m.get("project", d.project)
            d.category = m.get("category", d.category)
            return d

        cv_md, cv_pdf = self.root / "cv.md", self.root / "cv.pdf"
        if cv_md.exists() or cv_pdf.exists():
            text = cv_md.read_text(encoding="utf-8") if cv_md.exists() else _read_pdf(cv_pdf)
            out.append(enrich(EvidenceDoc(f"{P}-cv", "cv", "CV", text, "cv.pdf" if cv_pdf.exists() else "cv.md", P)))

        for f in sorted((self.root / "case_studies").glob("*.md")):
            md = f.read_text(encoding="utf-8")
            title = (re.search(r"^#\s+(.+)$", md, re.M) or [None, f.stem])[1]
            out.append(enrich(EvidenceDoc(f.stem, "case_study", title, md, f"case_studies/{f.name}", P,
                                          date=_md_field(md, "Date"), industry=_md_field(md, "Client industry"))))

        for d in sorted(p for p in (self.root / "repos").glob("*") if p.is_dir()):
            readme = (d / "README.md").read_text(encoding="utf-8") if (d / "README.md").exists() else ""
            code = "\n".join(f.read_text(encoding="utf-8", errors="ignore")[:4000]
                             for f in sorted(d.rglob("*")) if f.is_file() and f.suffix in CODE_EXT)
            out.append(enrich(EvidenceDoc(d.name, "repo", d.name, readme + "\n\n" + code, f"repos/{d.name}", P,
                                          parts={"readme": readme, "code": code})))

        rv = self.root / "reviews.json"
        if rv.exists():
            for r in json.loads(rv.read_text(encoding="utf-8")):
                out.append(enrich(EvidenceDoc(r["id"], "review", f"Client review ({r.get('stars', '?')} stars)",
                                              r["text"], "reviews.json", P, date=r.get("date"),
                                              project=r.get("project"), skills=r.get("skills", []))))

        pp = self.root / "past_proposals.jsonl"
        if pp.exists():
            for line in pp.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                out.append(enrich(EvidenceDoc(r["id"], "past_proposal", r.get("job_title", "Past proposal"), r["text"],
                                              "past_proposals.jsonl", P, date=r.get("date"), outcome=r.get("outcome"),
                                              skills=r.get("skills", []), industry=r.get("industry"),
                                              category=r.get("category"))))
        return out
