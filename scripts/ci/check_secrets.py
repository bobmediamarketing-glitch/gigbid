"""CI rule: no secrets in the repo. A fast local scan; CI also runs gitleaks over the full history.

Looks for provider keys, private keys and credential assignments in every tracked file except
.env.example (which must contain names only, no values) and the lockfiles.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = {
    "groq key": r"gsk_[A-Za-z0-9]{20,}",
    "anthropic key": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "openai-style key": r"\bsk-[A-Za-z0-9]{32,}",
    "langfuse secret": r"\bsk-lf-[A-Za-z0-9\-]{20,}",
    "github token": r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    "aws key": r"\bAKIA[0-9A-Z]{16}\b",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    # values only: shell expansions like ${JWT_SECRET:-$(...)} generate the secret at runtime
    "fernet key value": r"TOKEN_ENCRYPTION_KEY[ \t]*=[ \t]*(?![$\"'])[A-Za-z0-9_\-]{40,}=?",
    "jwt secret value": r"JWT_SECRET[ \t]*=[ \t]*(?![$\"'])[^\s#]{16,}",
}
SKIP_FILES = {"uv.lock", "apps/web/package-lock.json", "scripts/ci/check_secrets.py"}


def tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / p for p in out.splitlines() if p not in SKIP_FILES]


def main() -> int:
    bad = []
    for f in tracked():
        if not f.is_file() or f.suffix in (".pdf", ".png", ".jpg", ".gif", ".npz", ".sqlite"):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for name, pat in PATTERNS.items():
            for m in re.finditer(pat, text):
                bad.append(f"{f.relative_to(ROOT)}: {name} ({m.group(0)[:8]}...)")
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in env.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            v = v.split("#", 1)[0].strip()
            if v and not re.fullmatch(r"[A-Za-z0-9_./:@\-,*{}]*", v) or (k.strip().endswith(("_KEY", "_SECRET", "PASSWORD")) and v and "change-me" not in v):
                bad.append(f".env.example: {k.strip()} looks like it has a real value")
    for line in bad:
        print("FAIL", line)
    print(f"secrets check: {len(bad)} finding(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
