"""Settings, personas, portfolio uploads and the memory viewer."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, UploadFile

from agent.memory import style as style_memory
from apps.api import db
from apps.api.runtime import runtime, user_dir
from apps.api.schemas import MemoryView, OutcomeEntry, Persona, PortfolioFile, Settings, SettingsIn, StyleRule
from apps.api.security import User

router = APIRouter(prefix="/api", tags=["account"])
PERSONAS = db.ROOT / "data" / "personas"
UPLOAD_KINDS = {"cv": ("cv.pdf", (".pdf",)), "cv_md": ("cv.md", (".md",)),
                "case_study": ("case_studies/{name}", (".md",)), "reviews": ("reviews.json", (".json",)),
                "past_proposals": ("past_proposals.jsonl", (".jsonl",)), "repo_readme": ("repos/{stem}/README.md", (".md",))}
MAX_UPLOAD = 2 * 1024 * 1024


@router.get("/personas", response_model=list[Persona])
def personas() -> list[Persona]:
    out = []
    for d in sorted(p for p in PERSONAS.iterdir() if (p / "profile.json").exists()):
        pr = json.loads((d / "profile.json").read_text(encoding="utf-8"))
        out.append(Persona(id=pr["id"], name=pr["name"], title=pr["title"], skills=pr["skills"],
                           categories=pr["categories"], hourly_floor=pr["hourly_floor"], fixed_floor=pr["fixed_floor"]))
    return out


@router.get("/settings", response_model=Settings)
def get_settings(u: dict = User) -> Settings:
    return Settings(**db.get_settings(u["id"]))


@router.put("/settings", response_model=Settings)
def put_settings(body: SettingsIn, u: dict = User) -> Settings:
    data = body.model_dump(exclude_none=True)
    if data.get("persona") and not (PERSONAS / data["persona"] / "profile.json").exists():
        raise HTTPException(422, "unknown persona")
    s = db.put_settings(u["id"], data)
    if s.get("profile_mode") == "own" and s.get("own_profile"):
        _write_own_profile(u["id"], s)
    return Settings(**s)


def _write_own_profile(uid: int, s: dict) -> None:
    """Own-profile users get a portfolio folder the Portfolio MCP server indexes like a persona."""
    op = s["own_profile"]
    d = user_dir(uid) / "portfolio"
    (d / "case_studies").mkdir(parents=True, exist_ok=True)
    (d / "repos").mkdir(exist_ok=True)
    prof = {"id": "portfolio", "name": op["name"], "title": op["title"], "skills": op.get("skills", []),
            "hourly_floor": s.get("hourly_floor") or 25, "fixed_floor": s.get("fixed_floor") or 250,
            "categories": op.get("categories") or s.get("categories") or []}
    (d / "profile.json").write_text(json.dumps(prof, indent=1), encoding="utf-8")


@router.post("/portfolio/files", response_model=PortfolioFile, status_code=201)
async def upload(kind: str, file: UploadFile, u: dict = User) -> PortfolioFile:
    s = db.get_settings(u["id"])
    if s.get("profile_mode") != "own":
        raise HTTPException(409, "switch to 'own profile' in settings before uploading a portfolio")
    if kind not in UPLOAD_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(UPLOAD_KINDS)}")
    pattern, exts = UPLOAD_KINDS[kind]
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", file.filename or "upload")[:80]
    if not name.lower().endswith(exts):
        raise HTTPException(422, f"{kind} must be one of {exts}")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large (2 MB max)")
    stem = name.rsplit(".", 1)[0]
    rel = pattern.format(name=name, stem=stem)
    dest = (user_dir(u["id"]) / "portfolio" / rel).resolve()
    if not str(dest).startswith(str((user_dir(u["id"]) / "portfolio").resolve())):
        raise HTTPException(400, "bad path")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)  # the Portfolio server notices the new mtime and re-indexes incrementally
    return PortfolioFile(path=rel, size=len(data))


@router.get("/portfolio/files", response_model=list[PortfolioFile])
def list_files(u: dict = User) -> list[PortfolioFile]:
    root = user_dir(u["id"]) / "portfolio"
    if not root.exists():
        return []
    return [PortfolioFile(path=str(p.relative_to(root)).replace("\\", "/"), size=p.stat().st_size)
            for p in sorted(root.rglob("*")) if p.is_file()]


@router.get("/memory", response_model=MemoryView)
async def memory(u: dict = User) -> MemoryView:
    who, store = f"u{u['id']}", runtime.store
    rules = await style_memory.rules(store, who)
    pend = [i.value | {"key": i.key} for i in await store.asearch(("style_obs", who), limit=100)]
    promoted = {r["key"] for r in rules}
    outc = [i.value for i in await store.asearch(("outcome", who), limit=100)]
    return MemoryView(style=[StyleRule(**r) for r in rules],
                      style_pending=[StyleRule(**r) for r in pend if r["key"] not in promoted],
                      outcome=[OutcomeEntry(**o) for o in outc])


@router.delete("/memory/style/{key}", status_code=204)
async def forget_style(key: str, u: dict = User) -> None:
    await style_memory.forget(runtime.store, f"u{u['id']}", key)


@router.delete("/memory/outcome/{category}", status_code=204)
async def forget_outcome(category: str, u: dict = User) -> None:
    await runtime.store.adelete(("outcome", f"u{u['id']}"), category)
